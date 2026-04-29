# Election Night Operator Guide

## May 5, 2026 — Indiana + Ohio Primaries

### Pre-Election (May 4)

1. **Verify API is healthy:**
   ```bash
   curl http://178.156.243.51:8200/api/health
   ```

2. **Backup database:**
   ```bash
   ssh root@178.156.243.51 "cd /opt/national-elections/repo && /opt/national-elections/venv/bin/python scrapers/runner.py backup"
   ```

3. **Discover Indiana's active election URL:**
   ```bash
   # Check the ENR site for the active election slug
   curl -s "https://enr.indianavoters.in.gov/site/index.html" | grep -i "2026\|primary\|election"

   # Try the likely direct URL
   curl -s -o /dev/null -w "%{http_code}" "https://enr.indianavoters.in.gov/archive/2026Primary/download/AllOfficeResults.json"
   ```
   Update `scrapers/configs/indiana.yaml` → set `live_slug` to the discovered value.

4. **Test Ohio live feed:**
   ```bash
   ssh root@178.156.243.51 "cd /opt/national-elections/repo && /opt/national-elections/venv/bin/python scrapers/ohio_live.py --once"
   ```

5. **Pull latest code:**
   ```bash
   ssh root@178.156.243.51 "bash /opt/national-elections/repo/deploy/pull-and-run.sh"
   ```

### Election Night (May 5)

1. **Start Ohio live poller** (tmux session, survives SSH disconnect):
   ```bash
   ssh root@178.156.243.51
   tmux new -s ohio-live
   cd /opt/national-elections/repo
   /opt/national-elections/venv/bin/python scrapers/ohio_live.py --poll 2>&1 | tee /opt/national-elections/data/logs/ohio-live.log
   # Ctrl-B D to detach
   ```

2. **Start Indiana live poller:**
   ```bash
   tmux new -s indiana-live
   cd /opt/national-elections/repo
   /opt/national-elections/venv/bin/python scrapers/runner.py live --state IN 2>&1 | tee /opt/national-elections/data/logs/indiana-live.log
   # Ctrl-B D to detach
   ```

3. **Monitor progress:**
   ```bash
   # Tail both logs
   ssh root@178.156.243.51 "tail -f /opt/national-elections/data/logs/ohio-live.log"
   ssh root@178.156.243.51 "tail -f /opt/national-elections/data/logs/indiana-live.log"

   # Check row counts
   ssh root@178.156.243.51 "sqlite3 /opt/national-elections/data/elections.db 'SELECT state, COUNT(*) as races FROM races GROUP BY state'"

   # Check import_runs
   ssh root@178.156.243.51 "sqlite3 /opt/national-elections/data/elections.db 'SELECT state, status, started_at FROM import_runs ORDER BY started_at DESC LIMIT 10'"
   ```

4. **Verify frontend:**
   - Visit the Vercel deployment
   - Check `/in/live` and `/oh/live` for updating results
   - Verify county results are rendering

### Post-Election

1. **Stop live pollers:**
   ```bash
   ssh root@178.156.243.51 "tmux kill-session -t ohio-live; tmux kill-session -t indiana-live"
   ```

2. **Final backup:**
   ```bash
   ssh root@178.156.243.51 "cd /opt/national-elections/repo && /opt/national-elections/venv/bin/python scrapers/runner.py backup"
   ```

3. **Check quality:**
   ```bash
   ssh root@178.156.243.51 "sqlite3 /opt/national-elections/data/elections.db 'SELECT * FROM data_quality_checks ORDER BY checked_at DESC LIMIT 20'"
   ```

### Troubleshooting

- **API down:** `ssh root@178.156.243.51 "systemctl restart national-elections-api && journalctl -u national-elections-api --no-pager -n 20"`
- **Scraper 403/404:** Check if the SOS endpoint URL changed. May need to update config YAML.
- **DB locked:** Only one writer at a time. Check if another scraper is running: `ps aux | grep python`
- **Reattach tmux:** `ssh root@178.156.243.51 "tmux attach -t ohio-live"`
