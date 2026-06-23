#!/usr/bin/env python3
"""
Dashboard de Projetos — JumperFour
Dash app com tema dark, identidade visual JumperFour.
Dados sempre refletem o estado atual do banco (replace-only).
"""

import os, sys, subprocess
from datetime import datetime

import dash
from dash import dcc, html, Input, Output, State, callback, dash_table
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import psycopg2
import psycopg2.extras

# ─── Config ───────────────────────────────────────────────────
DATABASE_URL = "postgresql://postgres@localhost:5432/dashboard_projetos"
IMPORT_SCRIPT = os.path.expanduser("~/dashboard/import.py")
HOST = "0.0.0.0"
PORT = 8050

# ─── JumperFour Brand Colors ──────────────────────────────────
JF = {
    "bg": "#032B34",
    "bg_card": "#1A3A44",
    "bg_sidebar": "#032B34",
    "border": "#2A3842",
    "accent": "#338F5C",
    "accent_light": "#A6E17D",
    "accent_dark": "#395A31",
    "text": "#E1E1E1",
    "text_muted": "#8AA0A8",
    "text_bright": "#FFFFFF",
    "on_track": "#27AE60",
    "off_track": "#E74C3C",
    "at_risk": "#E67E22",
    "chart_seq": ["#A6E17D", "#338F5C", "#395A31", "#2A3842", "#D4A017", "#C0392B"],
}


# ─── Database ─────────────────────────────────────────────────
def get_db():
    return psycopg2.connect(DATABASE_URL)


def get_last_extracao():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT filename, imported_at, row_count FROM dash_extracoes ORDER BY imported_at DESC LIMIT 1")
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def load_data(estagios=None, responsaveis=None, tags=None, ocultar_concluidos=True):
    """Load filtered data from DB. Returns a DataFrame."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    where = []
    params = []

    if estagios:
        where.append("p.estagio = ANY(%s)")
        params.append(estagios)

    if responsaveis:
        where.append("p.responsavel = ANY(%s)")
        params.append(responsaveis)

    if tags:
        tag_conditions = []
        for tag in tags:
            if ":" in tag:
                cat, val = tag.split(":", 1)
                tag_conditions.append(
                    f"EXISTS (SELECT 1 FROM jsonb_array_elements(p.tags_jsonb) AS t "
                    f"WHERE t->>'cat' = %s AND t->>'val' = %s)"
                )
                params.extend([cat.strip(), val.strip()])
        if tag_conditions:
            where.append("(" + " OR ".join(tag_conditions) + ")")

    if ocultar_concluidos:
        where.append("p.estagio != 'Done'")

    where_clause = " AND ".join(where) if where else "TRUE"

    sql = f"""
        SELECT
            p.id, p.external_id, p.active, p.nome, p.responsavel,
            p.estagio, p.data_inicio, p.data_fim, p.status_atualizacao,
            p.tags_raw, p.tags_jsonb
        FROM dash_projetos p
        WHERE {where_clause}
        ORDER BY p.nome
    """
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Parse tags_jsonb into columns for charting
    df["tags_plano"] = df["tags_jsonb"].apply(
        lambda x: [t["val"] for t in x if t.get("cat") == "Plano"] if x else []
    )
    df["tags_prazo"] = df["tags_jsonb"].apply(
        lambda x: [t["val"] for t in x if t.get("cat") == "Prazo"] if x else []
    )
    df["tags_sist"] = df["tags_jsonb"].apply(
        lambda x: [t["val"] for t in x if t.get("cat") == "Sist"] if x else []
    )

    return df


def get_filter_options():
    """Get available options for each filter dimension."""
    conn = get_db()
    cur = conn.cursor()

    options = {}

    cur.execute("SELECT DISTINCT p.estagio FROM dash_projetos p ORDER BY p.estagio")
    options["estagios"] = [r[0] for r in cur.fetchall() if r[0]]

    cur.execute("SELECT DISTINCT p.responsavel FROM dash_projetos p ORDER BY p.responsavel")
    options["responsaveis"] = [r[0] for r in cur.fetchall() if r[0]]

    cur.execute("""
        SELECT DISTINCT t->>'cat' AS cat, t->>'val' AS val
        FROM dash_projetos p, jsonb_array_elements(p.tags_jsonb) AS t
        WHERE t->>'cat' IN ('Plano', 'Prazo')
        ORDER BY cat, val
    """)
    options["tags"] = [f'{r[0]}:{r[1]}' for r in cur.fetchall()]

    cur.close()
    conn.close()
    return options


# ─── Charts ───────────────────────────────────────────────────
def kpi_card(value, label, color):
    return html.Div([
        html.Div(value, style={
            "fontSize": 36, "fontWeight": 700, "color": color,
            "fontFamily": "Arial Black, Arial, sans-serif"
        }),
        html.Div(label, style={
            "fontSize": 13, "color": JF["text_muted"],
            "textTransform": "uppercase", "letterSpacing": "1px",
            "marginTop": 4
        }),
    ], style={
        "background": JF["bg_card"],
        "borderRadius": 12, "padding": "20px 24px",
        "textAlign": "center", "flex": "1",
        "border": f"1px solid {JF['border']}",
    })

def chart_status(df):
    """Barra única horizontal com chunks proporcionais por status"""
    counts = df["status_atualizacao"].value_counts()
    colors_map = {"On Track": "#27AE60", "Off Track": "#E74C3C",
                  "At Risk": "#E67E22", "On Hold": "#3498DB", "Set Status": "#95A5A6", "Done": "#8E44AD"}

    fig = go.Figure()
    for status in counts.index:
        fig.add_trace(go.Bar(
            name=status,
            x=[counts[status]],
            y=[""],
            orientation="h",
            marker=dict(color=colors_map.get(status, JF["text_muted"])),
            text=str(counts[status]),
            textposition="inside",
            textfont=dict(color="#fff", size=14, weight=700),
            hovertemplate=f"{status}: {counts[status]}<extra></extra>",
        ))

    fig.update_layout(
        barmode="stack",
        title=dict(text="Status de Atualização", font=dict(color=JF["text_bright"], size=16), x=0.5),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=40, b=50, l=10, r=10),
        height=200,
        xaxis=dict(showgrid=False, visible=False),
        yaxis=dict(showgrid=False, visible=False),
        legend=dict(
            orientation="h",
            yanchor="top", y=-0.3,
            xanchor="center", x=0.5,
            font=dict(color=JF["text"], size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=True,
    )
    return fig


def chart_tag_values(all_vals, title, color):
    if not all_vals:
        return go.Figure()
    counts = pd.Series(all_vals).value_counts().sort_values(ascending=True)
    fig = go.Figure(data=[go.Bar(
        x=counts.values.tolist(),
        y=counts.index.tolist(),
        orientation="h",
        marker=dict(color=color),
        text=counts.values.tolist(),
        textposition="outside",
        textfont=dict(color=JF["text"], size=11),
    )])
    fig.update_layout(
        title=dict(text=title, font=dict(color=JF["text_bright"], size=14), x=0.5),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, visible=False),
        yaxis=dict(showgrid=False, color=JF["text"], tickfont=dict(size=11)),
        margin=dict(t=40, b=10, l=10, r=40),
        height=280,
    )
    return fig


def flatten_tags(df, col):
    vals = []
    for _, row in df.iterrows():
        v = row.get(col, [])
        if isinstance(v, list):
            vals.extend(v)
    return vals


# ─── Helpers ──────────────────────────────────────────────────
def chart_card(graph_component):
    return html.Div([graph_component], style={
        "background": JF["bg_card"], "borderRadius": 12,
        "padding": 8, "border": f"1px solid {JF['border']}",
    })

# ─── App Layout ──────────────────────────────────────────────
app = dash.Dash(__name__, title="Dashboard Projetos — JumperFour")
app._favicon = None

app.layout = html.Div([
    html.Div([
        # ── Sidebar ──
        html.Div([
            html.Div([
                html.Div("JF", style={
                    "fontSize": 32, "fontWeight": 900, "color": JF["accent_light"],
                    "fontFamily": "Arial Black, sans-serif", "letterSpacing": "-1px",
                }),
                html.Div("Dashboard Projetos", style={
                    "fontSize": 14, "color": JF["text_muted"],
                    "marginTop": 2,
                }),
                html.Div(id="sidebar-subtitle", style={
                    "fontSize": 11, "color": JF["text_muted"],
                    "marginTop": 8, "fontStyle": "italic",
                }),
            ], style={"padding": "24px 20px", "borderBottom": f"1px solid {JF['border']}"}),

            # Filters
            html.Div([
                html.Label("Estágio", style={"color": JF["text_muted"], "fontSize": 11, "textTransform": "uppercase", "letterSpacing": "1px"}),
                dcc.Dropdown(id="dd-estagio", multi=True,
                    value=["Booking", "CT - Contratos de Tecnologia", "🔄️SP/PR - Em andamento", "⏳SP/PR Em Planejamento"],
                    style={"marginTop": 6, "color": "#333", "fontSize": 13}),
            ], style={"padding": "16px 20px 8px"}),

            html.Div([
                html.Label("Responsável", style={"color": JF["text_muted"], "fontSize": 11, "textTransform": "uppercase", "letterSpacing": "1px"}),
                dcc.Dropdown(id="dd-responsavel", multi=True, style={"marginTop": 6, "color": "#333", "fontSize": 13}),
            ], style={"padding": "8px 20px"}),

            html.Div([
                html.Label("Tags", style={"color": JF["text_muted"], "fontSize": 11, "textTransform": "uppercase", "letterSpacing": "1px"}),
                dcc.Dropdown(id="dd-tags", multi=True, style={"marginTop": 6, "color": "#333", "fontSize": 13}),
            ], style={"padding": "8px 20px 8px"}),

            html.Div([
                dcc.Checklist(
                    id="chk-ocultar-concluidos",
                    options=[{"label": " Ocultar concluídos", "value": "ocultar"}],
                    value=["ocultar"],
                    style={"color": JF["text"], "fontSize": 13},
                    labelStyle={"display": "flex", "alignItems": "center", "gap": 6},
                    inputStyle={"accentColor": JF["accent"]},
                ),
            ], style={"padding": "4px 20px 16px"}),

            html.Div([
                html.Button("↺ Limpar Filtros", id="btn-clear", style={
                    "background": "transparent", "border": f"1px solid {JF['border']}",
                    "color": JF["text_muted"], "padding": "8px 16px",
                    "borderRadius": 8, "cursor": "pointer",
                    "fontSize": 12, "width": "100%",
                }),
            ], style={"padding": "0 20px 16px"}),

            html.Div(style={"flex": 1}),

            html.Div([
                html.Button("⟳ Atualizar Dados", id="btn-update", style={
                    "background": JF["accent"], "border": "none",
                    "color": "#fff", "padding": "12px 20px",
                    "borderRadius": 10, "cursor": "pointer",
                    "fontSize": 14, "fontWeight": 700,
                    "width": "100%",
                }),
            ], style={"padding": "16px 20px 24px", "borderTop": f"1px solid {JF['border']}"}),

        ], style={
            "width": 280, "minWidth": 280,
            "background": JF["bg_sidebar"],
            "borderRight": f"1px solid {JF['border']}",
            "display": "flex", "flexDirection": "column",
            "height": "100vh", "overflowY": "auto",
        }),

        # ── Main Content ──
        html.Div([
            html.Div([
                html.H1("Dashboard de Projetos", style={
                    "color": JF["text_bright"], "fontSize": 24,
                    "fontWeight": 700, "margin": 0,
                }),
                html.Div(id="header-subtitle", style={
                    "color": JF["text_muted"], "fontSize": 13,
                    "marginTop": 4,
                }),
            ], style={"padding": "24px 32px 8px"}),

            html.Div(id="kpi-row", style={
                "display": "flex", "gap": 16,
                "padding": "16px 32px",
            }),

            # Charts grid row 1
            html.Div([
                chart_card(dcc.Graph(id="chart-status", config={"displayModeBar": False})),
                chart_card(dcc.Graph(id="chart-plano", config={"displayModeBar": False})),
                chart_card(dcc.Graph(id="chart-prazo", config={"displayModeBar": False})),
            ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr", "gap": 16, "padding": "8px 32px"}),

            # Charts grid row 2 — removed

            # Table
            html.Div([
                html.H3("Projetos", style={
                    "color": JF["text_bright"], "fontSize": 16,
                    "margin": "0 0 12px 0",
                }),
                dash_table.DataTable(
                    id="table-projetos",
                    page_size=15,
                    style_table={"overflowY": "auto"},
                    style_header={
                        "background": JF["accent"],
                        "color": "#fff",
                        "fontWeight": 700,
                        "fontSize": 12,
                        "textTransform": "uppercase",
                    },
                    style_data={
                        "background": JF["bg_card"],
                        "color": JF["text"],
                        "fontSize": 12,
                        "padding": "6px 10px",
                        "border": f"1px solid {JF['border']}",
                        "fontFamily": "Arial, sans-serif",
                        "whiteSpace": "normal",
                        "height": "auto",
                        "textAlign": "left",
                    },
                    style_cell_conditional=[
                        {"if": {"column_id": "nome"}, "width": "25%", "minWidth": "180px"},
                        {"if": {"column_id": "tags_raw"}, "width": "20%", "minWidth": "140px"},
                        {"if": {"column_id": "responsavel"}, "width": "14%"},
                        {"if": {"column_id": "estagio"}, "width": "16%"},
                        {"if": {"column_id": "status_atualizacao"}, "width": "9%"},
                        {"if": {"column_id": "data_inicio"}, "width": "8%"},
                        {"if": {"column_id": "data_fim"}, "width": "8%"},
                    ],
                    style_data_conditional=[
                        {
                            "if": {"filter_query": '{status_atualizacao} = "Off Track"'},
                            "backgroundColor": "#3D2E0A",
                            "color": JF["text"],
                        },
                        {
                            "if": {"filter_query": '{status_atualizacao} = "At Risk"'},
                            "backgroundColor": "#3D0A0A",
                            "color": JF["text"],
                        },
                    ],
                    sort_action="native",
                    filter_action="native",
                ),
            ], style={
                "padding": "16px 32px 32px",
            }),

        ], style={
            "flex": 1,
            "background": JF["bg"],
            "overflowY": "auto",
            "height": "100vh",
        }),
    ], style={
        "display": "flex", "flexDirection": "row",
        "height": "100vh", "width": "100vw",
        "fontFamily": "Arial, sans-serif",
    }),
    dcc.Store(id="store-hidden-status", data=[]),
    dcc.Store(id="store-hidden-plano", data=[]),
    dcc.Store(id="store-hidden-prazo", data=[]),
])


# ─── Callbacks ────────────────────────────────────────────────

@callback(
    [Output("dd-estagio", "options"),
     Output("dd-responsavel", "options"),
     Output("dd-tags", "options"),
     Output("sidebar-subtitle", "children")],
    Input("btn-update", "n_clicks"),
    prevent_initial_call=False,
)
def populate_filters_and_info(_n):
    opts = get_filter_options()
    est_options = [{"label": s, "value": s} for s in opts["estagios"]]
    resp_options = [{"label": s, "value": s} for s in opts["responsaveis"]]
    tag_options = [{"label": s.replace(":", ": "), "value": s} for s in opts["tags"]]

    # Default estágios
    defaults = ["Booking", "CT - Contratos de Tecnologia",
                "🔄️SP/PR - Em andamento", "⏳SP/PR Em Planejamento"]
    est_value = [d for d in defaults if d in opts["estagios"]]
    tag_options = [{"label": s.replace(":", ": "), "value": s} for s in opts["tags"]]

    last = get_last_extracao()
    if last:
        fname, ts, count = last
        dt = ts.strftime("%d/%m/%Y %H:%M") if hasattr(ts, "strftime") else str(ts)[:19]
        subtitle = f"Atualizado: {fname} ({dt})"
    else:
        subtitle = "Nenhum dado importado"

    return est_options, resp_options, tag_options, subtitle


@callback(
    [Output("kpi-row", "children"),
     Output("header-subtitle", "children"),
     Output("chart-status", "figure"),
     Output("chart-plano", "figure"),
     Output("chart-prazo", "figure"),
     Output("table-projetos", "columns"),
     Output("table-projetos", "data"),
     Output("store-hidden-status", "data"),
     Output("store-hidden-plano", "data"),
     Output("store-hidden-prazo", "data")],
    [Input("dd-estagio", "value"),
     Input("dd-responsavel", "value"),
     Input("dd-tags", "value"),
     Input("chk-ocultar-concluidos", "value"),
     Input("store-hidden-status", "data"),
     Input("store-hidden-plano", "data"),
     Input("store-hidden-prazo", "data"),
     Input("btn-clear", "n_clicks"),
     Input("btn-update", "n_clicks")],
    prevent_initial_call=False,
)
def update_dashboard(estagios, responsaveis, tags, ocultar_val,
                         hidden_status, hidden_plano, hidden_prazo,
                         _clear, _update):
    ocultar = "ocultar" in (ocultar_val or [])
    ctx = dash.callback_context
    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""

    # Apply legend-based exclusion filters
    hidden_status = hidden_status or []
    hidden_plano = hidden_plano or []
    hidden_prazo = hidden_prazo or []

    if trigger_id == "btn-clear":
        estagios = None
        responsaveis = None
        tags = None
        hidden_status = []
        hidden_plano = []
        hidden_prazo = []

    merged_estagios = estagios if estagios else None
    merged_resps = responsaveis if responsaveis else None

    if trigger_id == "btn-update":
        # Run import BEFORE loading data
        import subprocess as sp
        try:
            result = sp.run(
                [sys.executable, IMPORT_SCRIPT],
                capture_output=True, text=True, timeout=120,
            )
        except Exception:
            pass

    df = load_data(
        estagios=merged_estagios,
        responsaveis=merged_resps,
        tags=tags if tags else None,
        ocultar_concluidos=ocultar,
    )

    # Apply exclusion filters for legend-hidden items
    if not df.empty:
        if hidden_status:
            for s in hidden_status:
                df = df[df['status_atualizacao'] != s]
        if hidden_plano:
            for v in hidden_plano:
                df = df[~df['tags_plano'].apply(lambda x: v in x if isinstance(x, list) else False)]
        if hidden_prazo:
            for v in hidden_prazo:
                df = df[~df['tags_prazo'].apply(lambda x: v in x if isinstance(x, list) else False)]

    total = len(df)
    on_track = len(df[df["status_atualizacao"] == "On Track"]) if total > 0 else 0
    off_track = len(df[df["status_atualizacao"] == "Off Track"]) if total > 0 else 0
    at_risk = len(df[df["status_atualizacao"] == "At Risk"]) if total > 0 else 0

    # Subtitle
    last = get_last_extracao()
    if last:
        fname, ts, count = last
        dt = ts.strftime("%d/%m/%Y %H:%M") if hasattr(ts, "strftime") else str(ts)[:19]
        subtitle = f"{count} projetos — exibindo {total}"
        if estagios or responsaveis or tags:
            subtitle += " (filtrado)"
        subtitle += f" — {fname} ({dt})"
    else:
        subtitle = "Nenhum dado importado"

    if df.empty:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=10, b=10, l=10, r=10),
        )
        return (
            [kpi_card("0", "TOTAL", JF["text"]),
             kpi_card("0", "ON TRACK", JF["on_track"]),
             kpi_card("0", "OFF TRACK", JF["off_track"]),
             kpi_card("0", "AT RISK", JF["at_risk"])],
            subtitle, empty_fig, empty_fig, empty_fig,
            [], [],
            [], [], [],
        )

    # KPI cards
    kpis = [
        kpi_card(str(total), "TOTAL", JF["text"]),
        kpi_card(str(on_track), "ON TRACK", JF["on_track"]),
        kpi_card(str(off_track), "OFF TRACK", JF["off_track"]),
        kpi_card(str(at_risk), "AT RISK", JF["at_risk"]),
    ]

    # Charts
    fig_status = chart_status(df)

    # Plano stacked bar
    plano_vals = flatten_tags(df, "tags_plano")
    plano_counts = pd.Series(plano_vals).value_counts()
    plano_tag_colors = {"Preparar": "#3498DB", "Atraso": "#E67E22",
                          "Sem datas": "#F39C12", "Sem tarefas": "#E74C3C",
                          "Sem responsáveis": "#F39C12", "Resp. em Tarefa Resumo": "#D4A017",
                          "OK": "#27AE60"}
    fig_plano = go.Figure()
    for val, cnt in plano_counts.items():
        fig_plano.add_trace(go.Bar(
            name=val, x=[cnt], y=[""], orientation="h",
            marker=dict(color=plano_tag_colors.get(val, "#95A5A6")),
            text=str(cnt), textposition="inside",
            textfont=dict(color="#fff", size=13, weight=700),
            hovertemplate=f"{val}: {cnt}<extra></extra>",
        ))
    fig_plano.update_layout(
        barmode="stack", height=200,
        title=dict(text="Tags — Plano", font=dict(color=JF["text_bright"], size=16), x=0.5),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=40, b=50, l=10, r=10),
        xaxis=dict(showgrid=False, visible=False),
        yaxis=dict(showgrid=False, visible=False),
        legend=dict(orientation="h", yanchor="top", y=-0.3, xanchor="center", x=0.5,
                    font=dict(color=JF["text"], size=10), bgcolor="rgba(0,0,0,0)",
                    itemclick=False),
        showlegend=True,
    )

    # Prazo stacked bar
    prazo_vals = flatten_tags(df, "tags_prazo")
    prazo_counts = pd.Series(prazo_vals).value_counts()
    prazo_tag_colors = {"Atrasado": "#E74C3C", "<=7 dias": "#E67E22",
                          "<=30 dias": "#F39C12", "Em dia": "#27AE60"}
    fig_prazo = go.Figure()
    for val, cnt in prazo_counts.items():
        fig_prazo.add_trace(go.Bar(
            name=val, x=[cnt], y=[""], orientation="h",
            marker=dict(color=prazo_tag_colors.get(val, "#95A5A6")),
            text=str(cnt), textposition="inside",
            textfont=dict(color="#fff", size=13, weight=700),
            hovertemplate=f"{val}: {cnt}<extra></extra>",
        ))
    fig_prazo.update_layout(
        barmode="stack", height=200,
        title=dict(text="Tags — Prazo", font=dict(color=JF["text_bright"], size=16), x=0.5),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=40, b=50, l=10, r=10),
        xaxis=dict(showgrid=False, visible=False),
        yaxis=dict(showgrid=False, visible=False),
        legend=dict(orientation="h", yanchor="top", y=-0.3, xanchor="center", x=0.5,
                    font=dict(color=JF["text"], size=10), bgcolor="rgba(0,0,0,0)",
                    itemclick=False),
        showlegend=True,
    )

    # Estágio e Responsável removidos

    # Table data
    table_df = df[["nome", "responsavel", "estagio", "status_atualizacao",
                    "data_inicio", "data_fim", "tags_raw"]].copy()
    table_df["data_inicio"] = table_df["data_inicio"].astype(str)
    table_df["data_fim"] = table_df["data_fim"].astype(str)

    columns = [
        {"name": "Projeto", "id": "nome"},
        {"name": "Responsável", "id": "responsavel"},
        {"name": "Estágio", "id": "estagio"},
        {"name": "Status", "id": "status_atualizacao"},
        {"name": "Início", "id": "data_inicio"},
        {"name": "Fim", "id": "data_fim"},
        {"name": "Tags", "id": "tags_raw"},
    ]
    data = table_df.to_dict("records")

    # Reset stores on btn-clear
    return (kpis, subtitle,
            fig_status, fig_plano, fig_prazo,
            columns, data,
            hidden_status, hidden_plano, hidden_prazo)


# ─── Restyle callbacks (legend click → hidden store) ─────

@callback(
    Output("store-hidden-status", "data"),
    Input("chart-status", "restyleData"),
    State("store-hidden-status", "data"),
    prevent_initial_call=True,
)
def on_legend_status(restyle, hidden):
    if not restyle or not isinstance(restyle, list) or len(restyle) < 2:
        return dash.no_update
    update, indices = restyle
    if not indices:
        return dash.no_update
    # Map known status values by index order
    STATUS_ORDER = ["On Track", "Off Track", "At Risk", "On Hold", "Set Status", "Done"]
    idx = indices[0]
    if idx >= len(STATUS_ORDER):
        return dash.no_update
    val = STATUS_ORDER[idx]
    if isinstance(update, dict) and "visible" in update:
        vis = update["visible"]
        hidden = hidden or []
        if vis == "legendonly" or vis is False:
            if val not in hidden:
                hidden = hidden + [val]
        else:
            hidden = [h for h in hidden if h != val]
    return hidden


@callback(
    Output("store-hidden-plano", "data"),
    Input("chart-plano", "restyleData"),
    State("chart-plano", "figure"),
    State("store-hidden-plano", "data"),
    prevent_initial_call=True,
)
def on_legend_plano(restyle, fig, hidden):
    if not restyle or not isinstance(restyle, list) or len(restyle) < 2:
        return dash.no_update
    update, indices = restyle
    if not indices:
        return dash.no_update
    idx = indices[0]
    traces = (fig or {}).get("data", [])
    if idx >= len(traces):
        return dash.no_update
    val = traces[idx].get("name", "")
    if not val:
        return dash.no_update
    hidden = hidden or []
    if isinstance(update, dict) and "visible" in update:
        vis = update["visible"]
        if vis == "legendonly" or vis is False:
            if val not in hidden:
                hidden = hidden + [val]
        else:
            hidden = [h for h in hidden if h != val]
    return hidden


@callback(
    Output("store-hidden-prazo", "data"),
    Input("chart-prazo", "restyleData"),
    State("chart-prazo", "figure"),
    State("store-hidden-prazo", "data"),
    prevent_initial_call=True,
)
def on_legend_prazo(restyle, fig, hidden):
    if not restyle or not isinstance(restyle, list) or len(restyle) < 2:
        return dash.no_update
    update, indices = restyle
    if not indices:
        return dash.no_update
    idx = indices[0]
    traces = (fig or {}).get("data", [])
    if idx >= len(traces):
        return dash.no_update
    val = traces[idx].get("name", "")
    if not val:
        return dash.no_update
    hidden = hidden or []
    if isinstance(update, dict) and "visible" in update:
        vis = update["visible"]
        if vis == "legendonly" or vis is False:
            if val not in hidden:
                hidden = hidden + [val]
        else:
            hidden = [h for h in hidden if h != val]
    return hidden


# ─── Main ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Dashboard rodando em http://{HOST}:{PORT}")
    app.run(debug=False, host=HOST, port=PORT)
