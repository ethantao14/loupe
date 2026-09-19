begin;

alter table public.memories add column embedding jsonb;

drop function public.insert_memory(text);

create function public.insert_memory(fact text, embedding jsonb default null)
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
    memory public.memories%rowtype;
begin
    insert into public.memories (fact, embedding)
    values (insert_memory.fact, insert_memory.embedding)
    returning * into memory;

    return to_jsonb(memory);
end;
$$;

revoke execute on function public.insert_memory(text, jsonb) from public;
revoke execute on function public.insert_memory(text, jsonb) from anon, authenticated;
grant execute on function public.insert_memory(text, jsonb) to service_role;

commit;
