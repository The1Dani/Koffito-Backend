#!/usr/bin/env bash
# Live end-to-end check against the real Supabase project + the local API on :8000.
# Needs .env with SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SERVICE_ROLE_KEY, KOFFITO_BACKEND_KEY.
set -euo pipefail
set -a; source .env; set +a
API=${API:-http://127.0.0.1:8000}
EMAIL="koffito-e2e-$(date +%s)@example.com"
PASS="E2e-$(openssl rand -hex 8)!"
svc_auth=(-H "apikey: $SUPABASE_SERVICE_ROLE_KEY")
case "$SUPABASE_SERVICE_ROLE_KEY" in sb_secret_*) ;; *) svc_auth+=(-H "authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY");; esac

step() { printf '\n=== %s\n' "$*"; }

step "service role bypasses the gate (profiles?select=id&limit=1)"
curl -sS "$SUPABASE_URL/rest/v1/profiles?select=id&limit=1" "${svc_auth[@]}"; echo

step "create confirmed test user $EMAIL"
USER_JSON=$(curl -sS -X POST "$SUPABASE_URL/auth/v1/admin/users" "${svc_auth[@]}" -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"email_confirm\":true,\"user_metadata\":{\"first_name\":\"E2E\"}}")
UID_=$(echo "$USER_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "user id: $UID_"
trap 'step "delete test user"; curl -sS -o /dev/null -w "%{http_code}\n" -X DELETE "$SUPABASE_URL/auth/v1/admin/users/$UID_" "${svc_auth[@]}"' EXIT

step "password grant → access token"
TOKEN=$(curl -sS -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" -H "apikey: $SUPABASE_PUBLISHABLE_KEY" \
  -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
echo "token: ${TOKEN:0:20}..."
auth=(-H "authorization: Bearer $TOKEN")

step "gate: user token straight at PostgREST WITHOUT backend key → expect 42501"
curl -sS -X POST "$SUPABASE_URL/rest/v1/rpc/get_me" -H "apikey: $SUPABASE_PUBLISHABLE_KEY" "${auth[@]}" -H 'content-type: application/json' -d '{}'; echo
step "gate: same call WITH backend key → expect the profile json"
curl -sS -X POST "$SUPABASE_URL/rest/v1/rpc/get_me" -H "apikey: $SUPABASE_PUBLISHABLE_KEY" "${auth[@]}" -H "x-koffito-backend-key: $KOFFITO_BACKEND_KEY" -H 'content-type: application/json' -d '{}'; echo

step "GET /me"
curl -sS "$API/me" "${auth[@]}"; echo
step "PATCH /me (name + onboarded)"
curl -sS -X PATCH "$API/me" "${auth[@]}" -H 'content-type: application/json' -d '{"display_name":"E2E Tester","favorite_coffee":"cortado","onboarded":true}'; echo
step "PUT /me/languages"
curl -sS -X PUT "$API/me/languages" "${auth[@]}" -H 'content-type: application/json' -d '{"languages":["en","ro"]}'; echo
step "PATCH /me/settings"
curl -sS -X PATCH "$API/me/settings" "${auth[@]}" -H 'content-type: application/json' -d '{"reminders_enabled":true}'; echo
step "GET /me/survey → expect 404 survey_not_found"
curl -sS -w ' [%{http_code}]' "$API/me/survey" "${auth[@]}"; echo
step "GET /events"
EVENTS=$(curl -sS "$API/events" "${auth[@]}"); echo "$EVENTS"
EID=$(echo "$EVENTS" | python3 -c 'import sys,json; e=json.load(sys.stdin); print(e[0]["id"] if e else "")')
step "POST /events/$EID/join before survey → expect 409 survey_incomplete"
curl -sS -w ' [%{http_code}]' -X POST "$API/events/$EID/join" "${auth[@]}"; echo
step "PUT /me/survey (completed)"
curl -sS -X PUT "$API/me/survey" "${auth[@]}" -H 'content-type: application/json' -d '{"survey_data":{"q1":["a"],"q2":["b","c"]},"completed":true}'; echo
step "POST join → expect 204"
curl -sS -o /dev/null -w '[%{http_code}]\n' -X POST "$API/events/$EID/join" "${auth[@]}"
step "GET /me/events"
curl -sS "$API/me/events" "${auth[@]}"; echo
step "POST confirm 24h → 204"
curl -sS -w ' [%{http_code}]' -X POST "$API/events/$EID/confirm" "${auth[@]}" -H 'content-type: application/json' -d '{"stage":"24h"}'; echo
step "POST reveal → expect 409 not_revealed_yet (or 204 if revealed)"
curl -sS -w ' [%{http_code}]' -X POST "$API/events/$EID/reveal" "${auth[@]}"; echo
step "PUT rating → expect 409 not_attended"
curl -sS -w ' [%{http_code}]' -X PUT "$API/events/$EID/rating" "${auth[@]}" -H 'content-type: application/json' -d '{"rating":5}'; echo
step "POST leave → 204"
curl -sS -o /dev/null -w '[%{http_code}]\n' -X POST "$API/events/$EID/leave" "${auth[@]}"
step "POST /reports"
curl -sS -w ' [%{http_code}]' -X POST "$API/reports" "${auth[@]}" -H 'content-type: application/json' -d "{\"event_id\":\"$EID\",\"reason\":\"other\",\"details\":\"end-to-end test report, please ignore\"}"; echo
step "GET /users/<self>"
curl -sS -w ' [%{http_code}]' "$API/users/$UID_" "${auth[@]}"; echo
step "GET /admin/events as non-admin → expect 403"
curl -sS -w ' [%{http_code}]' "$API/admin/events" "${auth[@]}"; echo
step "GET /me/venues"
curl -sS -w ' [%{http_code}]' "$API/me/venues" "${auth[@]}"; echo
step "reminders job (service role)"
uv run python -m koffito.jobs reminders 2>&1 | tail -3
step "clean up the e2e report row (service role)"
curl -sS -o /dev/null -w '[%{http_code}]\n' -X DELETE "$SUPABASE_URL/rest/v1/reports?reporter_id=eq.$UID_" "${svc_auth[@]}"
