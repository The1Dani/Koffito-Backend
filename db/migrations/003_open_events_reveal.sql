-- Open coffee talks now say when (and whether) the café is revealed. A non-blind talk shows
-- its café right away; a blind one keeps it hidden from people who haven't joined, even after
-- the reveal time (joined people see it through get_my_events).
drop function if exists public.get_open_events();
create function public.get_open_events()
returns table (
  id uuid,
  event_at timestamptz,
  reveal_at timestamptz,
  blind boolean,
  max_participants int,
  spots_left int,
  joined boolean,
  cafe jsonb
)
language sql stable set search_path = public
as $$
  select
    e.id,
    e.event_at,
    e.reveal_at,
    e.reveal_at > e.created_at,
    e.target_group_size,
    greatest(e.capacity - count(ep.id) filter (
      where ep.status not in ('cancelled', 'declined', 'no_show')
    ), 0)::int,
    coalesce(bool_or(ep.user_id = app.uid() and ep.status not in ('cancelled', 'declined')), false),
    case when e.reveal_at <= e.created_at then public.venue_card(e.default_venue_id) end
  from public.events e
  left join public.event_participants ep on ep.event_id = e.id
  where e.status = 'open' and e.event_at > now()
  group by e.id
  order by e.event_at;
$$;
