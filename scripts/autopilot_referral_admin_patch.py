from pathlib import Path


path = Path("admin_server.py")
text = path.read_text()
if "import referral_admin as referral_admin\n" not in text:
    old = "import referral_engine as referrals\nimport reminder_engine as reminders\n"
    new = "import referral_engine as referrals\nimport referral_admin as referral_admin\nimport reminder_engine as reminders\n"
    if text.count(old) != 1:
        raise SystemExit("admin import anchor mismatch")
    text = text.replace(old, new, 1)

old = """  if path=='/api/admin/referrals/accounts':
   if not self.authorized(): return self.require_auth()
   try:
    q=parse_qs(parsed.query); limit=int((q.get('limit') or ['100'])[0])
    return self.send_json({'accounts':referrals.list_accounts(limit),'rewardCents':referrals.configured_reward_cents()})
   except Exception as exc: return self.send_json({'ok':False,'error':str(exc)},400)
"""
new = """  if path=='/api/admin/referrals/accounts':
   if not self.authorized(): return self.require_auth()
   try:
    q=parse_qs(parsed.query); limit=int((q.get('limit') or ['100'])[0])
    return self.send_json(referral_admin.status(limit))
   except (TypeError,ValueError): return self.send_json({'ok':False,'error':'referral_request_invalid'},400)
   except Exception as exc: return self.send_json({'ok':False,'error':type(exc).__name__},500)
"""
if "return self.send_json(referral_admin.status(limit))" not in text:
    if text.count(old) != 1:
        raise SystemExit("referral accounts endpoint anchor mismatch")
    text = text.replace(old, new, 1)
path.write_text(text)

js_path = Path("admin/referrals.js")
js = js_path.read_text()
old = """    rrRender(data);
    if(badge){badge.textContent='ReferralWallet actif';badge.className='gsc-status online'}
    return data;
"""
new = """    rrRender(data);
    const integrity=data.integrity||{};
    if(badge){
      if(integrity.ok===true){badge.textContent='Ledger cohérent';badge.className='gsc-status online'}
      else if(integrity.state==='unavailable'){badge.textContent='Audit indisponible';badge.className='gsc-status offline'}
      else{
        const issues=Math.max(0,Number(integrity.issues||0));
        badge.textContent=`Ledger · ${issues} anomalie${issues===1?'':'s'}`;
        badge.className='gsc-status warning';
      }
    }
    return data;
"""
if "const integrity=data.integrity||{};" not in js:
    if js.count(old) != 1:
        raise SystemExit("referral UI anchor mismatch")
    js = js.replace(old, new, 1)
js_path.write_text(js)
