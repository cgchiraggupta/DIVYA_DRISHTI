# Deploy GPIO25 control button (Pi)

Repo files stay here; copy to the Pi when SSH is up (`divyadrishti.local` or link-local).

```bash
# From repo root
scp setup/hardware-integration/divyadrishti_control_button.py \
  pi@divyadrishti.local:/home/pi/
scp setup/hardware-integration/divyadrishti-control-button.service \
  pi@divyadrishti.local:/tmp/

ssh pi@divyadrishti.local '
  sudo mv /tmp/divyadrishti-control-button.service /etc/systemd/system/ &&
  sudo systemctl daemon-reload &&
  sudo systemctl enable --now divyadrishti-control-button.service &&
  systemctl status divyadrishti-control-button.service --no-pager
'
```

Rollback: `sudo systemctl disable --now divyadrishti-control-button.service`

Does not touch `divya_drishti_final.py` or the sensing unit definition.
