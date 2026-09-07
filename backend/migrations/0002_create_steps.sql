create table if not exists steps (
    id uuid primary key default gen_random_uuid(),
    message_id uuid not null references messages (id) on delete cascade,
    seq bigserial not null,
    kind text not null check (kind in ('thinking', 'tool_call', 'tool_result', 'answer')),
    tool_name text,
    detail text not null,
    created_at timestamptz not null default now()
);

-- Steps are always read for one message, in the order they happened.
create index if not exists steps_message_seq_idx on steps (message_id, seq);
