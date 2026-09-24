-- get_my_events: say whether the coffee talk is a "blind" one (café hidden
-- until reveal_at). Non-blind events get reveal_at = created_at.
drop function if exists public.get_my_events();
create function public.get_my_events()
returns table (
  id uuid,
  event_at timestamptz,
  reveal_at timestamptz,
  status text,
  participant_status participant_status,
  joined boolean,
  blind boolean,
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
  e.reveal_at > e.created_at,
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
