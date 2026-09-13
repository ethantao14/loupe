begin;

create table public.conversations (
    id uuid primary key default gen_random_uuid(),
    seq bigserial not null,
    title text,
    created_at timestamptz not null default now()
);

create index conversations_seq_idx on public.conversations (seq desc);

alter table public.conversations enable row level security;
revoke all on public.conversations from anon, authenticated;

alter table public.messages add column conversation_id uuid
    references public.conversations (id) on delete cascade;

do $$
declare
    earlier_conversation uuid;
    earlier_title text;
begin
    if exists (select 1 from public.messages where conversation_id is null) then
        select nullif(left(btrim(regexp_replace(content, '[[:space:]]+', ' ', 'g')), 60), '')
        into earlier_title
        from public.messages
        where role = 'user'
        order by seq
        limit 1;

        insert into public.conversations (title)
        values (coalesce(earlier_title, 'Earlier conversation'))
        returning id into earlier_conversation;

        update public.messages
        set conversation_id = earlier_conversation
        where conversation_id is null;
    end if;
end;
$$;

alter table public.messages alter column conversation_id set not null;
create index messages_conversation_seq_idx on public.messages (conversation_id, seq);

drop function if exists public.insert_exchange_with_steps(text, text, jsonb);

create or replace function public.insert_exchange_with_steps(
    conversation uuid,
    user_content text,
    reply_content text,
    steps jsonb
)
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
    selected_conversation uuid := conversation;
    user_message public.messages%rowtype;
    reply_message public.messages%rowtype;
    step jsonb;
    ordered_steps jsonb;
begin
    if selected_conversation is null then
        insert into public.conversations default values
        returning id into selected_conversation;
    end if;

    insert into public.messages (conversation_id, role, content)
    values (selected_conversation, 'user', user_content)
    returning * into user_message;

    insert into public.messages (conversation_id, role, content)
    values (selected_conversation, 'assistant', reply_content)
    returning * into reply_message;

    for step in
        select value
        from jsonb_array_elements(steps) with ordinality
        order by ordinality
    loop
        insert into public.steps (message_id, kind, tool_name, detail)
        values (
            reply_message.id,
            step ->> 'kind',
            step ->> 'tool_name',
            step ->> 'detail'
        );
    end loop;

    update public.conversations
    set title = nullif(left(btrim(regexp_replace(user_content, '[[:space:]]+', ' ', 'g')), 60), '')
    where id = selected_conversation and title is null;

    select coalesce(jsonb_agg(to_jsonb(s) order by s.seq), '[]'::jsonb)
    into ordered_steps
    from public.steps s
    where s.message_id = reply_message.id;

    return jsonb_build_object(
        'conversation_id', selected_conversation,
        'user', to_jsonb(user_message),
        'reply', to_jsonb(reply_message),
        'steps', ordered_steps
    );
end;
$$;

-- Functions in public are exposed as PostgREST RPC and default to being
-- executable by everyone, which would let the public anon key write rows.
-- Only the backend's service role may call this.
revoke execute on function public.insert_exchange_with_steps(uuid, text, text, jsonb) from public;
revoke execute on function public.insert_exchange_with_steps(uuid, text, text, jsonb) from anon, authenticated;
grant execute on function public.insert_exchange_with_steps(uuid, text, text, jsonb) to service_role;

commit;
