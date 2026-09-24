#!/usr/bin/env bash
set -euo pipefail
set -a; source .env; set +a
API=${API:-http://127.0.0.1:8000}
EMAIL="koffito-e2e-admin-$(date +%s)@example.com"; PASS="E2e-$(openssl rand -hex 8)!"
svc=(-H "apikey: $SUPABASE_SERVICE_ROLE_KEY")
case "$SUPABASE_SERVICE_ROLE_KEY" in sb_secret_*) ;; *) svc+=(-H "authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY");; esac
J=(-H 'content-type: application/json')
step() { printf '\n=== %s\n' "$*"; }
jget() { python3 -c "import sys,json; d=json.load(sys.stdin); print(eval('d$1'))"; }

step "create user + promote to admin via service role"
UID_=$(curl -sS -X POST "$SUPABASE_URL/auth/v1/admin/users" "${svc[@]}" "${J[@]}" -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"email_confirm\":true,\"user_metadata\":{\"first_name\":\"E2EAdmin\"}}" | jget '["id"]')
NEW_EID=""; VID=""
cleanup() {
  step "cleanup"
  [ -n "$NEW_EID" ] && curl -sS -o /dev/null -w 'events del [%{http_code}]\n' -X DELETE "$SUPABASE_URL/rest/v1/events?id=eq.$NEW_EID" "${svc[@]}"
  [ -n "$VID" ] && curl -sS -o /dev/null -w 'venue del [%{http_code}]\n' -X DELETE "$SUPABASE_URL/rest/v1/venues?id=eq.$VID" "${svc[@]}"
  curl -sS -o /dev/null -w 'reports del [%{http_code}]\n' -X DELETE "$SUPABASE_URL/rest/v1/reports?reporter_id=eq.$UID_" "${svc[@]}"
  curl -sS -o /dev/null -w 'user del [%{http_code}]\n' -X DELETE "$SUPABASE_URL/auth/v1/admin/users/$UID_" "${svc[@]}"
}
trap cleanup EXIT
curl -sS -X PATCH "$SUPABASE_URL/rest/v1/profiles?id=eq.$UID_" "${svc[@]}" "${J[@]}" -H 'prefer: return=representation' -d '{"is_admin":true}' | jget '[0]["is_admin"]'
TOKEN=$(curl -sS -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" -H "apikey: $SUPABASE_PUBLISHABLE_KEY" "${J[@]}" -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" | jget '["access_token"]')
auth=(-H "authorization: Bearer $TOKEN")

step "GET /me → isAdmin true"
curl -sS "$API/me" "${auth[@]}" | jget '["isAdmin"]'
step "GET /admin/events (paged, includes default_venue_id)"
curl -sS "$API/admin/events?limit=2" "${auth[@]}" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("total", d["total"], "first keys:", sorted(d["items"][0]) if d["items"] else [])'
step "POST /admin/events (5h from now, visible location)"
EVENT_AT=$(date -u -v+5H +%Y-%m-%dT%H:%M:%SZ)
NEW=$(curl -sS -w '\n%{http_code}' -X POST "$API/admin/events" "${auth[@]}" "${J[@]}" -d "{\"event_at\":\"$EVENT_AT\",\"title\":\"e2e event\",\"location_hidden\":false,\"target_group_size\":3}")
echo "$NEW" | tail -1; NEW_EID=$(echo "$NEW" | head -1 | jget '["id"]'); echo "event id: $NEW_EID"
step "GET /admin/events/{id}"
curl -sS -w ' [%{http_code}]' "$API/admin/events/$NEW_EID" "${auth[@]}" | python3 -c 'import sys; s=sys.stdin.read(); print(s[-60:])'
step "PATCH /admin/events/{id}"
curl -sS -X PATCH "$API/admin/events/$NEW_EID" "${auth[@]}" "${J[@]}" -d '{"title":"e2e event edited","capacity":8}' | jget '["title"], d["capacity"]'
step "PATCH with reveal_at > event_at → expect 422 constraint_violation"
curl -sS -w ' [%{http_code}]' -X PATCH "$API/admin/events/$NEW_EID" "${auth[@]}" "${J[@]}" -d '{"reveal_at":"2030-01-01T00:00:00Z"}'; echo
step "user completes survey and joins the new event"
curl -sS -o /dev/null -w 'survey [%{http_code}] ' -X PUT "$API/me/survey" "${auth[@]}" "${J[@]}" -d '{"survey_data":{"q1":["a"]}}'
curl -sS -o /dev/null -w 'join [%{http_code}]\n' -X POST "$API/events/$NEW_EID/join" "${auth[@]}"
step "GET /admin/events/{id}/participants"
curl -sS "$API/admin/events/$NEW_EID/participants" "${auth[@]}" | python3 -c 'import sys,json; r=json.load(sys.stdin)[0]; print(r["status"], r["profile"], "reminded_24h_at:", r["reminded_24h_at"])'
step "reminders job → expect sent_24h=1 (event in 5h, status joined)"
uv run python -m koffito.jobs reminders 2>&1 | grep -o 'ReminderStats.*'
curl -sS "$API/admin/events/$NEW_EID/participants" "${auth[@]}" | python3 -c 'import sys,json; r=json.load(sys.stdin)[0]; print("reminded_24h_at:", r["reminded_24h_at"])'
step "reminders_enabled=false + reset stamp → job must skip (nested embedded filter)"
curl -sS -o /dev/null -w 'settings [%{http_code}] ' -X PATCH "$API/me/settings" "${auth[@]}" "${J[@]}" -d '{"reminders_enabled":false}'
curl -sS -o /dev/null -w 'reset [%{http_code}]\n' -X PATCH "$SUPABASE_URL/rest/v1/event_participants?event_id=eq.$NEW_EID" "${svc[@]}" "${J[@]}" -d '{"reminded_24h_at":null}'
uv run python -m koffito.jobs reminders 2>&1 | grep -o 'ReminderStats.*'
step "venues: list, create, patch, soft-delete, list inactive"
curl -sS "$API/admin/venues" "${auth[@]}" | python3 -c 'import sys,json; print("active venues:", len(json.load(sys.stdin)))'
VID=$(curl -sS -X POST "$API/admin/venues" "${auth[@]}" "${J[@]}" -d '{"name":"e2e café","address":"nowhere 1","capacity":10,"rating":4.5,"popular_times":[1,2,3,4,5,6,7]}' | jget '["id"]'); echo "venue id: $VID"
curl -sS -X PATCH "$API/admin/venues/$VID" "${auth[@]}" "${J[@]}" -d '{"capacity":12}' | jget '["capacity"]'
curl -sS -o /dev/null -w 'delete [%{http_code}]\n' -X DELETE "$API/admin/venues/$VID" "${auth[@]}"
curl -sS "$API/admin/venues/$VID" "${auth[@]}" | jget '["is_active"]'
step "reports: file one, list as admin, triage"
RID=$(curl -sS -X POST "$API/reports" "${auth[@]}" "${J[@]}" -d "{\"event_id\":\"$NEW_EID\",\"reason\":\"other\",\"details\":\"admin e2e report, ignore me\"}" | jget '["id"]')
curl -sS "$API/admin/reports?status=open" "${auth[@]}" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("open reports:", d["total"], "reported_by:", d["items"][0]["reported_by"])'
curl -sS -X PATCH "$API/admin/reports/$RID" "${auth[@]}" "${J[@]}" -d '{"status":"resolved"}' | jget '["status"], d["handled_by"]'
step "matchmaking + venues skeleton jobs run without writing"
uv run python -m koffito.jobs all 2>&1 | grep -oE '(job \w+ finished.*|WARN.*)' | head -5
