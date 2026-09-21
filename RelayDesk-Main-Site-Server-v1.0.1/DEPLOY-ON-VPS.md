# Deploy RelayDesk on a VPS

These steps are written for Ubuntu 22.04/24.04 or Debian 12.

## 1. Upload the ZIP

Upload `RelayDesk-Complete-v1.0.0.zip` to the server using your host's file manager, SFTP or SCP.

## 2. Connect to the server

```bash
ssh root@YOUR_VPS_IP
```

## 3. Install Docker

```bash
apt update
apt install -y docker.io docker-compose-v2 unzip
systemctl enable --now docker
```

If your provider does not supply `docker-compose-v2`, install Docker Compose using Docker's official repository.

## 4. Unzip the package

```bash
mkdir -p /opt/relaydesk
unzip RelayDesk-Complete-v1.0.0.zip -d /opt/relaydesk
cd /opt/relaydesk/RelayDesk-Complete-v1.0.0
```

## 5. Start RelayDesk

```bash
chmod +x setup.sh backup.sh
./setup.sh
```

Copy the generated control-panel password shown on screen.

## 6. Allow the temporary port

If UFW is enabled:

```bash
ufw allow 8080/tcp
```

Open `http://YOUR_VPS_IP:8080` and confirm the login page appears.

## 7. Connect Telegram

Use the website's one-time setup. Never paste Telegram verification codes into SSH commands or send them to another person.

## 8. Test before the full import

Use **Import test** with 10 posts. Confirm text and media appear correctly. Then run the full import and enable the live relay.

## 9. Add HTTPS before regular use

Point a domain to the VPS and configure a reverse proxy. The included `nginx.conf.example` can be adapted after installing Certbot. Once HTTPS works, close public port 8080 and bind it to localhost in `docker-compose.yml`:

```yaml
ports:
  - "127.0.0.1:8080:8080"
```

## 10. Check operation

```bash
cd /opt/relaydesk/RelayDesk-Complete-v1.0.0
docker compose ps
docker compose logs -f --tail=100
```

The container uses `restart: unless-stopped`, so it resumes after a VPS restart.

