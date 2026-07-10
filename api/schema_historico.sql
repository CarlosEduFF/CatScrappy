-- Tabela de histórico: episódios de anime / capítulos de mangá já vistos.
-- Rodar no SQL Editor do Supabase (uma vez).
--
-- Espelha o padrão da tabela `favoritos`: acesso sempre pela API com a
-- service-role key, que filtra por user_id; o RLS fica ativo por segurança.
--
-- Chaves de identificação de um item visto:
--   tipo         'anime' | 'manga'
--   site         ex.: 'animefire', 'mangadex'
--   item_id      id/URL da SÉRIE ou MANGÁ (o pai)
--   episodio_id  id/URL do EPISÓDIO ou CAPÍTULO específico (o filho)
--
-- item_id permite contar "quantos vistos" por série (barra de progresso);
-- episodio_id é o que marca cada episódio/capítulo individual.

create table if not exists historico (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    tipo text not null,
    site text not null,
    item_id text not null,
    episodio_id text not null,
    numero text default '',
    titulo text default '',
    visto_em timestamptz not null default now(),
    -- Um mesmo episódio/capítulo aparece uma única vez por usuário.
    unique (user_id, tipo, site, item_id, episodio_id)
);

alter table historico enable row level security;

-- Consulta comum: "todos os vistos de uma série" (para pintar a lista).
create index if not exists historico_user_item_idx
    on historico (user_id, tipo, site, item_id);
