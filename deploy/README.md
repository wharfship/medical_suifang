# Deployment Files

This directory stores the files needed to run the Gradio app with `systemd` on the server.

## Files

- `medical-suifang.service`: systemd service template for the Gradio app
- `medical_suifang.env.example`: environment variable example file

## Server Assumptions

These files are preconfigured for the following server paths:

- Project directory: `/home/suifang/medical_suifang`
- Virtual environment: `/home/suifang/.venv`
- App entrypoint: `/home/suifang/medical_suifang/app.py`
- Service user: `suifang`

If your server paths change later, update `medical-suifang.service` before installing it.

## Install On The Server

Run these commands from the project root after pulling the latest code:

```bash
sudo cp deploy/medical-suifang.service /etc/systemd/system/medical-suifang.service
sudo cp deploy/medical_suifang.env.example /etc/medical_suifang.env
sudo chmod 600 /etc/medical_suifang.env
sudo vi /etc/medical_suifang.env
```

Replace the placeholder value in `/etc/medical_suifang.env` with your real `DASHSCOPE_API_KEY`.

Then reload and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable medical-suifang
sudo systemctl start medical-suifang
```

## Verify

Check status:

```bash
sudo systemctl status medical-suifang
```

View logs:

```bash
sudo journalctl -u medical-suifang -f
```

If the service is healthy, the app should continue to be reachable at:

```text
http://<your-server-ip>:7860
```

## Update Workflow

When you update the code later:

```bash
git pull
sudo systemctl restart medical-suifang
```
