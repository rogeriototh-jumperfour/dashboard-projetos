-- Dashboard Projetos — JumperFour
-- Schema: replace-only. Cada import substitui todos os dados.

-- ============================================================
-- 1. Extrações (log de auditoria — cada import)
-- ============================================================
CREATE TABLE IF NOT EXISTS dash_extracoes (
    id              SERIAL PRIMARY KEY,
    filename        VARCHAR(255) NOT NULL,
    imported_at     TIMESTAMP DEFAULT NOW(),
    row_count       INTEGER DEFAULT 0
);

-- ============================================================
-- 2. Projetos (sempre o estado atual — truncado a cada import)
-- ============================================================
CREATE TABLE IF NOT EXISTS dash_projetos (
    id                  SERIAL PRIMARY KEY,

    external_id         VARCHAR(255),
    active              BOOLEAN DEFAULT TRUE,
    nome                VARCHAR(500),
    responsavel         VARCHAR(255),
    estagio             VARCHAR(255),
    data_inicio         DATE,
    data_fim            DATE,
    status_atualizacao  VARCHAR(50),

    tags_raw            TEXT,
    tags_jsonb          JSONB DEFAULT '[]'::JSONB,

    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dash_projetos_estagio   ON dash_projetos(estagio);
CREATE INDEX IF NOT EXISTS idx_dash_projetos_resp       ON dash_projetos(responsavel);
CREATE INDEX IF NOT EXISTS idx_dash_projetos_status     ON dash_projetos(status_atualizacao);
CREATE INDEX IF NOT EXISTS idx_dash_projetos_tags       ON dash_projetos USING GIN (tags_jsonb);

-- ============================================================
-- 3. View: tags normalizadas
-- ============================================================
CREATE OR REPLACE VIEW dash_vw_tags AS
SELECT
    p.id AS projeto_id,
    p.nome,
    p.responsavel,
    p.estagio,
    p.status_atualizacao,
    p.data_inicio,
    p.data_fim,
    t->>'cat' AS tag_categoria,
    t->>'val' AS tag_valor
FROM dash_projetos p
CROSS JOIN LATERAL jsonb_array_elements(p.tags_jsonb) AS t;
