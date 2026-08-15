# Deploy Hindi wake-word listener ("Hey Divya Drishti") — Pi

Repo files stay here; copy to the Pi when SSH is up (`divyadrishti.local` or link-local).
**Do not run any of this on the Pi until told to.** This doc is the reference for when
that go-ahead is given — it is not a record of anything already done.

## Step 0 — verify this can even run on this chip (do this first, changes nothing)

This project's compute is a Raspberry Pi Zero W (single-core ARM1176JZF-S, ARMv6, no
NEON) per `divyadrishti-sensing-start.sh`. There is an open Picovoice issue
(`Picovoice/porcupine#1414`) where their ARM11/ARMv6 build crashes with `SIGILL`
because the shipped binary contains NEON instructions — and Picovoice's own reply says
they no longer officially support that chip family. Confirm the exact chip and test the
engine with a harmless built-in keyword before trusting a trained custom model:

```bash
ssh pi@divyadrishti.local
cat /proc/cpuinfo | grep -i "model name\|Hardware\|Revision"
pip3 install --user pvporcupine
python3 -c "
import pvporcupine
p = pvporcupine.create(access_key='ENTER_A_TEST_KEY', keywords=['porcupine'])
print('OK:', p.sample_rate, p.frame_length)
p.delete()
"
```

If that crashes with an illegal instruction / `SIGILL`, stop here — this needs to move
to the phone instead, not the glasses. If it prints `OK: ...`, proceed below.

## One-time setup (Picovoice Console, not the Pi)

1. Free account at <https://console.picovoice.ai/>, get an `AccessKey`. Never commit it
   or paste it in chat/logs.
2. Train a custom wake word: language **Hindi**, phrase **"Divya Drishti"** (test
   without "Hey" too — shorter phrases have lower false-reject/false-accept rates).
   Platform: **Raspberry Pi** (re-check against Step 0's exact chip result). Download
   the `.ppn` file.
3. Because Hindi is non-English, also grab `porcupine_params_hi.pv` from the language
   model files in Picovoice's Porcupine GitHub repo (`lib/common/`).

## Deploy

```bash
# From repo root
scp setup/hardware-integration/divyadrishti_wake_word.py \
  pi@divyadrishti.local:/home/pi/
scp setup/hardware-integration/divyadrishti-wake-word.service \
  pi@divyadrishti.local:/tmp/

# Copy the trained model files (from your machine, not committed to the repo)
ssh pi@divyadrishti.local 'mkdir -p /home/pi/.divyadrishti/wake_word'
scp keyword.ppn pi@divyadrishti.local:/home/pi/.divyadrishti/wake_word/keyword.ppn
scp porcupine_params_hi.pv \
  pi@divyadrishti.local:/home/pi/.divyadrishti/wake_word/porcupine_params_hi.pv

# AccessKey — create this file on the Pi directly, never through scp of a
# local file that might get committed by accident
ssh pi@divyadrishti.local 'cat > /home/pi/.divyadrishti/porcupine.env <<EOF
PORCUPINE_ACCESS_KEY=paste-your-key-here
EOF'

ssh pi@divyadrishti.local '
  pip3 install --user pvporcupine pvrecorder &&
  sudo mv /tmp/divyadrishti-wake-word.service /etc/systemd/system/ &&
  sudo systemctl daemon-reload &&
  sudo systemctl enable --now divyadrishti-wake-word.service &&
  systemctl status divyadrishti-wake-word.service --no-pager
'
```

## Verify

```bash
ssh pi@divyadrishti.local 'journalctl -u divyadrishti-wake-word.service -f'
```
Say the trained phrase and confirm a "Wake word detected" log line appears, and that the
phone receives the same describe result it gets from the Describe button / GPIO25 button.

## Rollback

```bash
sudo systemctl disable --now divyadrishti-wake-word.service
```

Does not touch `divya_drishti_final.py`, the sensing unit, or the control-button
service/script. Independent listener, calls the existing local API only.
