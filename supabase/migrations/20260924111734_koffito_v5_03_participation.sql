-- Koffito v5: confirmations, attendance feedback, reveal tracking and reminder
-- bookkeeping on event_participants, plus the RPCs the backend calls for them.

alter table public.event_participants
  add column if not exists attended boolean,
  add column if not exists attendance_note text,
  add column if not exists reveal_opened_at timestamptz,
  add column if not exists reminded_24h_at timestamptz,
  add column if not exists reminded_3h_at timestamptz;

comment on column public.event_participants.attended is
  'The user''s own answer to "did this coffee talk happen?"; null until answered.';
comment on column public.event_participants.reminded_24h_at is
  'Set by the backend reminder job once the 24h reminder went out.';
comment on column public.event_participants.reminded_3h_at is
  'Set by the backend reminder job once the 3h reminder went out.';

-- 24h / 3h confirmation from the participant.
create or replace function public.confirm_event(p_event_id uuid, p_stage text)
returns void
language plpgsql
security definer
set search_path = 'public'
as $$
declare
  v_uid uuid := auth.uid();
  v_event public.events%rowtype;
begin
  if v_uid is null then
    raise exception 'not_authenticated';
  end if;
  if p_stage not in ('24h', '3h') then
    raise exception 'invalid_stage';
  end if;

  select * into v_event from public.events where id = p_event_id;
  if not found or v_event.status in ('cancelled', 'completed', 'draft') or v_event.event_at <= now() then
    raise exception 'event_not_confirmable';
  end if;

  if p_stage = '24h' then
    update public.event_participants
      set status = 'confirmed_24h', confirmed_24h_at = coalesce(confirmed_24h_at, now())
    where event_id = p_event_id and user_id = v_uid
      and status in ('joined', 'matched');
  else
    update public.event_participants
      set status = 'confirmed_3h',
          confirmed_24h_at = coalesce(confirmed_24h_at, now()),
          confirmed_3h_at = coalesce(confirmed_3h_at, now())
    where event_id = p_event_id and user_id = v_uid
      and status in ('joined', 'matched', 'confirmed_24h');
  end if;

  if not found then
    raise exception 'nothing_to_confirm';
  end if;
end;
$$;

-- "Did this coffee talk happen?" after the meetup, with an optional note.
create or replace function public.report_attendance(p_event_id uuid, p_happened boolean, p_note text default null)
returns void
language plpgsql
security definer
set search_path = 'public'
as $$
declare
  v_uid uuid := auth.uid();
begin
  if v_uid is null then
    raise exception 'not_authenticated';
  end if;

  update public.event_participants ep
    set attended = p_happened,
        attendance_note = nullif(trim(coalesce(p_note, '')), ''),
        status = case when p_happened then ep.status else 'no_show' end
  from public.events e
  where e.id = ep.event_id
    and ep.event_id = p_event_id
    and ep.user_id = v_uid
    and ep.status not in ('cancelled', 'declined')
    and e.event_at <= now();

  if not found then
    raise exception 'nothing_to_confirm';
  end if;
end;
$$;

-- The user opened a revealed café; remembered so the card stays open.
create or replace function public.open_reveal(p_event_id uuid)
returns void
language plpgsql
security definer
set search_path = 'public'
as $$
begin
  update public.event_participants ep
    set reveal_opened_at = coalesce(ep.reveal_opened_at, now())
  from public.events e
  where e.id = ep.event_id
    and ep.event_id = p_event_id
    and ep.user_id = auth.uid()
    and ep.status not in ('cancelled', 'declined')
    and e.reveal_at <= now();

  if not found then
    raise exception 'not_revealed_yet';
  end if;
end;
$$;

revoke all on function public.confirm_event(uuid, text) from public, anon;
revoke all on function public.report_attendance(uuid, boolean, text) from public, anon;
revoke all on function public.open_reveal(uuid) from public, anon;
grant execute on function public.confirm_event(uuid, text) to authenticated, service_role;
grant execute on function public.report_attendance(uuid, boolean, text) to authenticated, service_role;
grant execute on function public.open_reveal(uuid) to authenticated, service_role;

-- get_my_events now also carries the participant's feedback and reveal state.
drop function if exists public.get_my_events();
create function public.get_my_events()
returns table (
  id uuid,
  event_at timestamptz,
  reveal_at timestamptz,
  status text,
  participant_status participant_status,
  joined boolean,
  location_hidden boolean,
  reveal_opened boolean,
  max_participants int,
  cafe jsonb,
  participants jsonb,
  attended boolean,
  attendance_note text,
  my_rating smallint,
  my_comment text
)
language sql
stable
security definer
set search_path = 'public'
as $$
select
  e.id,
  e.event_at,
  e.reveal_at,
  case
    when ep.status in ('cancelled', 'declined', 'no_show')
      or e.status = 'cancelled' then 'cancelled'
    when e.status = 'completed' then 'completed'
    when ep.status in ('confirmed_24h', 'confirmed_3h') then 'confirmed'
    else 'pending'
  end,
  ep.status,
  ep.status not in ('cancelled', 'declined'),
  e.reveal_at > now(),
  ep.reveal_opened_at is not null,
  greatest(e.target_group_size, coalesce(mates.total, 0)),
  case when e.reveal_at <= now()
    then public.venue_card(coalesce(g.venue_id, e.default_venue_id)) end,
  case when e.reveal_at <= now()
    then coalesce(mates.cards, '[]'::jsonb) end,
  ep.attended,
  ep.attendance_note,
  r.rating,
  r.comment
from public.event_participants ep
join public.events e on e.id = ep.event_id
left join public.groups g on g.id = ep.group_id
left join public.event_ratings r on r.event_id = e.id and r.user_id = ep.user_id
left join lateral (
  select
    count(*)::int as total,
    jsonb_agg(public.profile_card(m.user_id) order by m.joined_at)
      filter (where m.user_id <> ep.user_id) as cards
  from public.event_participants m
  where m.group_id = ep.group_id
    and m.status not in ('cancelled', 'declined')
) mates on ep.group_id is not null
where ep.user_id = auth.uid()
  and e.status <> 'draft'
order by e.event_at;
$$;
revoke all on function public.get_my_events() from public, anon;
grant execute on function public.get_my_events() to authenticated, service_role;
