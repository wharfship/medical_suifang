# Deployment Files

This directory stores the files needed to run the Gradio app with `systemd` and expose it through `nginx`.

## Files

- `medical-suifang.service`: systemd service template for the Gradio app
- `medical_suifang.env.example`: environment variable example file
- `nginx-medical-suifang.conf`: nginx reverse proxy template for domain access

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

## IP Access With Nginx

Use nginx if you want users to open the app with a normal address such as `http://your-server-ip` instead of `http://your-server-ip:7860`.

### Before You Start

Make sure all of the following are true:

- The Gradio app is already running through `systemd`
- The server firewall already allows port `80`

### Install Nginx

On Ubuntu or Debian:

```bash
sudo apt update
sudo apt install -y nginx
```

### Install The Nginx Config

This template is already configured for direct IP access, so you can copy it into nginx directly:

```bash
sudo cp deploy/nginx-medical-suifang.conf /etc/nginx/conf.d/medical-suifang.conf
```

If nginx is still showing its welcome page, disable the packaged default site first:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
```

### Check And Reload

```bash
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
sudo systemctl status nginx
```

### Verify

After nginx starts cleanly, open:

```text
http://your-server-ip
```

At that point, you no longer need to expose `:7860` to users.

## Optional: Switch To A Domain Later

If you buy a domain later, update:

```nginx
server_name _;
```

to something like:

```nginx
server_name your-domain.com www.your-domain.com;
```

Then point the domain's `A` record to this server and reload nginx.
