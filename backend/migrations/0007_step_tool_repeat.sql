begin;

alter table public.steps drop constraint if exists steps_kind_check;
alter table public.steps add constraint steps_kind_check
    check (kind in ('thinking', 'tool_call', 'tool_result', 'tool_error', 'tool_repeat', 'answer', 'memory'));

commit;
