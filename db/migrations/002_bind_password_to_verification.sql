-- Stop "pre-registration" account takeover.
--
-- Before: someone could register a victim's email with their own password; when the victim
-- later confirmed the address, that password still opened the account.
-- Now every registration's confirmation link carries the password (hash) and name chosen in
-- that registration. Confirming applies them, so the account always ends up with the
-- credentials of whoever clicked the link in the mailbox, and the other pending links die.
alter table public.email_tokens
  add column if not exists password_hash text,
  add column if not exists display_name text;
