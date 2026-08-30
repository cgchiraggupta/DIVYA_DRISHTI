-- Buzzer support: a health column matching camera_ok/mic_ok, and lowering
-- the vibration_intensity floor from 40 to 20 -- the motor can now go
-- quieter because the buzzer (continuous, distance-scaled beep) covers the
-- alerting the motor used to carry alone. The Pi and the app clamp already
-- allow 20; this migration is what let the app's cloud RPC path (checked
-- BEFORE the direct nearby push) stop rejecting it first.

alter table public.device_status
  add column if not exists buzzer_ok boolean;

alter table public.device_setting_requests
  drop constraint if exists device_setting_requests_vibration_intensity_check,
  add constraint device_setting_requests_vibration_intensity_check
    check (vibration_intensity between 20 and 100);

create or replace function public.request_device_settings(
  pairing_code_input text,
  client_request_id_input uuid,
  sensitivity_mm_input integer,
  feedback_mode_input text,
  volume_input integer,
  vibration_intensity_input integer,
  base_revision_input bigint default 0
)
returns setof public.device_setting_requests
language plpgsql
security definer
set search_path = public
as $$
declare
  target_device public.devices;
  existing_request public.device_setting_requests;
  created_request public.device_setting_requests;
  current_revision bigint := 0;
begin
  if client_request_id_input is null then
    raise exception 'A request ID is required' using errcode = '22023';
  end if;
  if sensitivity_mm_input not between 1000 and 2500 then
    raise exception 'Detection range must be between 1000 and 2500 mm' using errcode = '22023';
  end if;
  if feedback_mode_input not in ('audio', 'vibration', 'both') then
    raise exception 'Unsupported feedback mode' using errcode = '22023';
  end if;
  if volume_input not between 20 and 100 then
    raise exception 'Volume must be between 20 and 100' using errcode = '22023';
  end if;
  if vibration_intensity_input not between 20 and 100 then
    raise exception 'Vibration intensity must be between 20 and 100' using errcode = '22023';
  end if;

  -- Serialize all requests for the same glasses before inspecting revision or
  -- superseding a queued snapshot.
  select * into target_device
  from public.devices
  where pairing_code = upper(trim(pairing_code_input))
  for update;

  if not found then
    raise exception 'Device pairing code is invalid' using errcode = 'P0002';
  end if;

  select * into existing_request
  from public.device_setting_requests
  where client_request_id = client_request_id_input;

  if found then
    if existing_request.device_id <> target_device.id then
      raise exception 'Request ID belongs to another device' using errcode = '22023';
    end if;
    return next existing_request;
    return;
  end if;

  select revision into current_revision
  from public.device_settings
  where device_id = target_device.id;
  current_revision := coalesce(current_revision, 0);

  if coalesce(base_revision_input, 0) <> current_revision then
    raise exception 'Settings changed on the glasses. Refresh and try again.' using errcode = '40001';
  end if;

  -- A newer save replaces only work the Pi has not started. An applying
  -- request remains leased and cannot be silently overwritten.
  update public.device_setting_requests
  set state = 'superseded', completed_at = now(),
      error_code = 'superseded', error_message = 'Replaced by a newer settings request.'
  where device_id = target_device.id and state = 'queued';

  begin
    insert into public.device_setting_requests (
      device_id, client_request_id, base_revision, sensitivity_mm,
      feedback_mode, volume, vibration_intensity
    ) values (
      target_device.id, client_request_id_input, current_revision,
      sensitivity_mm_input, feedback_mode_input, volume_input,
      vibration_intensity_input
    ) returning * into created_request;
  exception when unique_violation then
    select * into existing_request
    from public.device_setting_requests
    where client_request_id = client_request_id_input;
    if found and existing_request.device_id = target_device.id then
      return next existing_request;
      return;
    end if;
    raise;
  end;

  return next created_request;
end;
$$;

revoke all on function public.request_device_settings(text, uuid, integer, text, integer, integer, bigint) from public;
grant execute on function public.request_device_settings(text, uuid, integer, text, integer, integer, bigint) to anon, authenticated;
