-- Domínios das fontes definidos pelo admin e pedidos de implementação.
-- Rodar no SQL Editor do Supabase (uma vez).
--
-- Mesmo padrão de `favoritos`/`historico`: acesso só pela API com a
-- service-role key; o RLS fica ativo (sem policies = nenhum acesso direto).

-- Um endereço por fonte. `site` é o id da fonte no app (ex.: 'redetoons').
-- Sem linha = a fonte usa o endereço de fábrica que está no código.
create table if not exists fontes_dominios (
    site text primary key,
    url text not null,
    atualizado_por text not null default '',
    atualizado_em timestamptz not null default now()
);

alter table fontes_dominios enable row level security;

-- Sites que o admin colou mas ainda não têm scraper (ou cujo scraper quebrou):
-- fila de "implementar via código". Um registro por host.
create table if not exists fontes_pendentes (
    host text primary key,
    url text not null,
    nota text not null default '',
    pedido_por text not null default '',
    criado_em timestamptz not null default now()
);

alter table fontes_pendentes enable row level security;
