-- Koffito v6: two RPCs the FastAPI backend needs on top of v5.
--
-- * rate_event: `authenticated` may only UPDATE (rating, comment) on event_ratings, so a
--   PostgREST upsert (which also sets event_id / user_id) is impossible; do it server-side,
--   with the same "you attended" rule as the RLS insert policy.
-- * admin_list_events: `authenticated` deliberately cannot SELECT events.default_venue_id
--   (it would leak the café of blind events to every user). Admins read events through
--   this function instead; PostgREST filters/order/count apply to its rows as usual.

create or replace function public.rate_event(p_event_id uuid, p_rating smallint, p_comment text default '')
returns jsonb
language plpgsql
security definer
set search_path = 'public'
as $$
declare
  v_uid uuid := auth.uid();
  v_row public.event_ratings%rowtype;
begin
  if v_uid is null then
    raise exception 'not_authenticated';
  end if;
  if p_rating is null or p_rating < 1 or p_rating > 5 then
    raise exception 'invalid_rating';
  end if;
  if not public.attended_event(p_event_id) then
    raise exception 'not_attended';
  end if;

  insert into public.event_ratings (event_id, user_id, rating, comment)
  values (p_event_id, v_uid, p_rating, coalesce(p_comment, ''))
  on conflict (event_id, user_id) do update
    set rating = excluded.rating,
        comment = excluded.comment
  returning * into v_row;

  return jsonb_build_object(
    'event_id', v_row.event_id,
    'rating', v_row.rating,
    'comment', v_row.comment,
    'created_at', v_row.created_at,
    'updated_at', v_row.updated_at
  );
end;
$$;
revoke all on function public.rate_event(uuid, smallint, text) from public, anon;
grant execute on function public.rate_event(uuid, smallint, text) to authenticated, service_role;

create or replace function public.admin_list_events()
returns setof public.events
language sql
stable
security definer
set search_path = 'public'
as $$
  select * from public.events where public.is_admin();
$$;
revoke all on function public.admin_list_events() from public, anon;
grant execute on function public.admin_list_events() to authenticated, service_role;
