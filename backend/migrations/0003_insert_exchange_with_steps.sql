create or replace function insert_exchange_with_steps(
    user_content text,
    reply_content text,
    steps jsonb
)
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
    user_message public.messages%rowtype;
    reply_message public.messages%rowtype;
    step jsonb;
    ordered_steps jsonb;
begin
    insert into public.messages (role, content)
    values ('user', user_content)
    returning * into user_message;

    insert into public.messages (role, content)
    values ('assistant', reply_content)
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

    select coalesce(jsonb_agg(to_jsonb(s) order by s.seq), '[]'::jsonb)
    into ordered_steps
    from public.steps s
    where s.message_id = reply_message.id;

    return jsonb_build_object(
        'user', to_jsonb(user_message),
        'reply', to_jsonb(reply_message),
        'steps', ordered_steps
    );
end;
$$;

-- Functions in public are exposed as PostgREST RPC and default to being
-- executable by everyone, which would let the public anon key write rows.
-- Only the backend's service role may call this.
revoke execute on function public.insert_exchange_with_steps(text, text, jsonb) from public;
revoke execute on function public.insert_exchange_with_steps(text, text, jsonb) from anon, authenticated;
grant execute on function public.insert_exchange_with_steps(text, text, jsonb) to service_role;
