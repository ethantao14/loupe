begin;

alter table public.conversations add column visitor_id uuid;
alter table public.memories add column visitor_id uuid;

do $$
declare
    earlier_visitor uuid := gen_random_uuid();
begin
    update public.conversations set visitor_id = earlier_visitor;
    update public.memories set visitor_id = earlier_visitor;
    raise notice 'Existing data visitor ID: %', earlier_visitor;
end;
$$;

alter table public.conversations alter column visitor_id set not null;
alter table public.memories alter column visitor_id set not null;
create index conversations_visitor_seq_idx on public.conversations (visitor_id, seq desc);
create index memories_visitor_seq_idx on public.memories (visitor_id, seq desc);

drop function public.insert_memory(text, jsonb);

create function public.insert_memory(visitor uuid, fact text, embedding jsonb default null)
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
    memory public.memories%rowtype;
begin
    insert into public.memories (visitor_id, fact, embedding)
    values (visitor, insert_memory.fact, insert_memory.embedding)
    returning * into memory;

    return to_jsonb(memory);
end;
$$;

revoke execute on function public.insert_memory(uuid, text, jsonb) from public;
revoke execute on function public.insert_memory(uuid, text, jsonb) from anon, authenticated;
grant execute on function public.insert_memory(uuid, text, jsonb) to service_role;

drop function public.insert_exchange_with_steps(uuid, text, text, jsonb);

create or replace function public.insert_exchange_with_steps(
    visitor uuid,
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
        insert into public.conversations (visitor_id) values (visitor)
        returning id into selected_conversation;
    elsif not exists (
        select 1 from public.conversations
        where id = selected_conversation and visitor_id = visitor
    ) then
        raise exception 'Conversation not found.';
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
    where id = selected_conversation and visitor_id = visitor and title is null;

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
revoke execute on function public.insert_exchange_with_steps(uuid, uuid, text, text, jsonb) from public;
revoke execute on function public.insert_exchange_with_steps(uuid, uuid, text, text, jsonb) from anon, authenticated;
grant execute on function public.insert_exchange_with_steps(uuid, uuid, text, text, jsonb) to service_role;

commit;
