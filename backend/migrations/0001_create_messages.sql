create table if not exists messages (
    id uuid primary key default gen_random_uuid(),
    seq bigserial not null,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    created_at timestamptz not null default now()
);

-- Both rows of an exchange are inserted in one statement and share a created_at,
-- so seq is what orders them.
create index if not exists messages_seq_idx on messages (seq);
