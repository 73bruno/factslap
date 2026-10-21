-- FactSlap index: every passage we retrieve is kept, so the index grows with use.
-- Hybrid search = Postgres full-text (lexical) + pgvector (semantic), fused with reciprocal rank fusion.

create extension if not exists vector;

create table if not exists passages (
  id            text primary key,              -- e.g. 's2:12345:body:0', 'epmc:PMC123:0'
  source        text not null,
  title         text not null,
  body          text not null,
  url           text,
  year          int,
  authors       text[] default '{}',
  venue         text,
  doi           text,
  corpus_id     bigint,
  study_type    text not null default 'other',
  lang          text not null default 'en',
  embedding     vector(768),
  fts           tsvector generated always as (
                  to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(body, ''))
                ) stored,
  first_seen    timestamptz not null default now()
);

create index if not exists passages_fts_idx on passages using gin (fts);
create index if not exists passages_embedding_idx on passages using hnsw (embedding vector_cosine_ops);
create index if not exists passages_corpus_idx on passages (corpus_id);

-- One row per check: what was asked, what we answered, how long it took and what it cost.
-- No personal data: the IP is stored only as a salted hash for rate-limit analysis.
create table if not exists checks (
  id            bigint generated always as identity primary key,
  created_at    timestamptz not null default now(),
  claim         text not null,
  lang          text,
  claim_embedding vector(768),
  verdict       text,
  confidence    real,
  evidence_ids  text[],
  verification_passed boolean,
  latency_ms    int,
  cost_usd      real,
  ip_hash       text,
  result        jsonb
);

create index if not exists checks_claim_embedding_idx on checks using hnsw (claim_embedding vector_cosine_ops);

-- Hybrid search with reciprocal rank fusion (pattern from the Supabase docs, using the 'simple'
-- text config so it works for English and Spanish alike).
create or replace function hybrid_search(
  query_text text,
  query_embedding vector(768),
  match_count int default 20,
  full_text_weight float default 1,
  semantic_weight float default 1,
  rrf_k int default 60
)
returns setof passages
language sql stable
as $$
with full_text as (
  select id, row_number() over (order by ts_rank_cd(fts, websearch_to_tsquery('simple', query_text)) desc) as rank_ix
  from passages
  where fts @@ websearch_to_tsquery('simple', query_text)
  limit least(match_count, 30) * 2
),
semantic as (
  select id, row_number() over (order by embedding <=> query_embedding) as rank_ix
  from passages
  where embedding is not null
  order by embedding <=> query_embedding
  limit least(match_count, 30) * 2
)
select p.*
from full_text
full outer join semantic on full_text.id = semantic.id
join passages p on p.id = coalesce(full_text.id, semantic.id)
order by
  coalesce(1.0 / (rrf_k + full_text.rank_ix), 0.0) * full_text_weight +
  coalesce(1.0 / (rrf_k + semantic.rank_ix), 0.0) * semantic_weight
  desc
limit least(match_count, 30);
$$;

-- Semantic cache: a previous check of an almost identical claim, if recent enough.
create or replace function similar_check(query_embedding vector(768), max_distance float default 0.08, max_age_days int default 30)
returns setof checks
language sql stable
as $$
  select * from checks
  where claim_embedding is not null
    and verification_passed
    and created_at > now() - make_interval(days => max_age_days)
    and (claim_embedding <=> query_embedding) < max_distance
  order by claim_embedding <=> query_embedding
  limit 1;
$$;
