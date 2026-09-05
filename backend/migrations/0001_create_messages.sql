create table if not exists messages (
    id uuid primary key default gen_random_uuid(),
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    created_at timestamptz not null default now()
);

create index if not exists messages_created_at_idx on messages (created_at);
