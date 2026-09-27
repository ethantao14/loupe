#!/usr/bin/env bash
# Run on your own machine. Prompts for the demo's secrets without echoing them,
# applies every migration to the demo database, and writes the server's env file.
# Usage: bash deploy/configure.sh ubuntu@SERVER_IP
set -euo pipefail

SERVER="${1:?Usage: bash deploy/configure.sh ubuntu@SERVER_IP}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/loupe_oracle}"
cd "$(dirname "$0")/.."
# psql ships with Postgres.app on macOS but is not on the PATH by default.
export PATH="/Applications/Postgres.app/Contents/Versions/latest/bin:$PATH"
command -v psql >/dev/null || { echo "psql is required." >&2; exit 1; }

ask() {
  local prompt=$1 secret=${2:-} value
  if [[ -n "$secret" ]]; then
    read -r -s -p "$prompt: " value && echo >&2
  else
    read -r -p "$prompt: " value
  fi
  [[ -n "$value" ]] || { echo "A value is required." >&2; exit 1; }
  printf '%s' "$value"
}

echo "Values are read from your keyboard and never printed."
database_url=$(ask "Supabase session pooler connection string (with your password filled in)" secret)
supabase_url=$(ask "Supabase project URL, like https://abcd.supabase.co")
service_key=$(ask "Supabase service_role key" secret)
anthropic_key=$(ask "Anthropic API key for the demo" secret)
frontend_origin=$(ask "Frontend origin, like https://loupe-demo.vercel.app (use http://localhost:3000 for now if unknown)")

echo "==> Applying migrations to the demo database"
for migration in backend/migrations/*.sql; do
  echo "    $migration"
  psql "$database_url" -q -v ON_ERROR_STOP=1 -f "$migration" >/dev/null
done

echo "==> Writing /etc/loupe/backend.env on $SERVER"
env_file=$(sed \
  -e "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$anthropic_key|" \
  -e "s|^SUPABASE_URL=.*|SUPABASE_URL=$supabase_url|" \
  -e "s|^SUPABASE_SERVICE_KEY=.*|SUPABASE_SERVICE_KEY=$service_key|" \
  -e "s|^FRONTEND_ORIGIN=.*|FRONTEND_ORIGIN=$frontend_origin|" \
  deploy/backend.env.example)
# The file goes over ssh on stdin, so no secret appears in a command line.
printf '%s\n' "$env_file" | ssh -i "$SSH_KEY" "$SERVER" \
  'sudo install -d -m 755 /etc/loupe && sudo tee /etc/loupe/backend.env >/dev/null && sudo chmod 600 /etc/loupe/backend.env'
echo "Done. The server has its settings; the database has every migration."
