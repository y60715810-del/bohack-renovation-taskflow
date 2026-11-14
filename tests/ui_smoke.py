"""Optional Playwright checks for the rendered application; see docs/UI_REDESIGN.md."""
from playwright.sync_api import sync_playwright
import argparse
import json
import secrets
from pathlib import Path

parser = argparse.ArgumentParser(description='Browser regression checks; use disposable test databases.')
parser.add_argument('--app-url', default='http://127.0.0.1:8774')
parser.add_argument('--demo-url', default='http://127.0.0.1:8775')
parser.add_argument('--artifacts-dir', default='/tmp/taskflow-ui-artifacts')
args = parser.parse_args()
artifacts = Path(args.artifacts_dir)
artifacts.mkdir(parents=True, exist_ok=True)
errors=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 page=b.new_page(viewport={'width':1440,'height':1000})
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(args.app_url,wait_until='networkidle')
 page.get_by_role('heading',name='回到你的项目').wait_for()
 page.get_by_role('button',name='注册账号',exact=True).click()
 assert page.locator('#authForm [name=role] option').count()==5
 page.get_by_role('button',name='登录',exact=True).click()
 page.get_by_role('button',name='了解四方如何协作').click()
 frame=page.frame_locator('#story-scene iframe')
 frame.get_by_role('heading',name='把每一方的依据，放在一起。').wait_for()
 frame.get_by_role('button',name='播放协作构建').click()
 page.wait_for_timeout(1000)
 assert frame.locator('swarm-rebuild').count()>0, 'Swarm overlay missing'
 assert frame.locator('swarm-rebuild').evaluate('(e)=>getComputedStyle(e).filter')=='grayscale(1)'
 page.screenshot(path=str(artifacts/'swarm-active.png'))
 page.get_by_role('button',name='关闭演示').click()
 page.locator('#story-scene iframe').wait_for(state='detached')
 assert page.evaluate('document.activeElement.hasAttribute("data-open-story")')
 for width in (375,768,1440):
  page.set_viewport_size({'width':width,'height':900})
  page.screenshot(path=str(artifacts/f'taskflow-login-{width}.png'),full_page=True)
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Login overflow {width}'
 page.emulate_media(reduced_motion='reduce')
 page.get_by_role('button',name='了解四方如何协作').click()
 frame=page.frame_locator('#story-scene iframe')
 frame.get_by_role('heading').first.wait_for()
 assert frame.locator('#play').is_hidden()
 page.keyboard.press('Escape')
 assert not page.locator('dialog').is_visible()
 page.emulate_media(reduced_motion='no-preference')
 page.get_by_role('button',name='注册账号',exact=True).click()
 username='ui_'+secrets.token_hex(6)
 password=secrets.token_urlsafe(18)
 page.locator('#authForm [name=username]').fill(username)
 page.locator('#authForm [name=name]').fill('界面回归测试')
 page.locator('#authForm [name=role]').select_option('coordinator')
 page.locator('#authForm [name=password]').fill(password)
 page.locator('#authForm button[type=submit]').click()
 page.locator('#createProject').wait_for()
 page.locator('#createProject [name=title]').fill('UI 合成测试项目')
 page.locator('#createProject [name=baseline]').fill('测试装修原方案，供界面回归使用。')
 page.locator('#createProject [name=reference]').fill('UI-D01')
 page.locator('#createProject button').click()
 page.locator('#inviteForm button').wait_for()
 page.locator('#inviteForm [name=role]').select_option('owner')
 page.locator('#inviteForm button').click()
 page.locator('#inviteResult input').first.wait_for()
 assert page.locator('#inviteResult input').count()==2
 page.locator('#logout').click()
 page.get_by_role('button',name='登录',exact=True).click()
 page.locator('#authForm [name=username]').fill(username)
 page.locator('#authForm [name=password]').fill(password)
 page.locator('#authForm button[type=submit]').click()
 page.locator('#inviteForm').wait_for()
 page.set_viewport_size({'width':1440,'height':1000})
 page.goto(args.demo_url+'/?show=1',wait_until='networkidle')
 page.locator('.sidebar').wait_for()
 for role in ('coordinator','designer','contractor','owner'):
  page.locator('.demo-switch summary').click()
  page.locator(f'.demo-switch [data-demo-role={role}]').click()
  page.wait_for_timeout(200)
  for tab in ('overview','schedule','changes','tasks','members','activity'):
   page.locator(f'.nav [data-tab={tab}]').click()
   page.wait_for_timeout(100)
   assert page.locator('.content').inner_text().strip(),(role,tab,'blank')
   for viewport_width in (375,768):
    page.set_viewport_size({'width':viewport_width,'height':900})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Overflow {role} {tab} {viewport_width}'
   page.set_viewport_size({'width':1440,'height':1000})
   if role=='coordinator' and tab=='members':
    assert page.locator('#inviteForm button').is_visible(), 'Invitation button lost in malformed markup'
   if tab in ('overview','schedule','tasks') and role in ('coordinator','contractor'):
    page.screenshot(path=str(artifacts/f'taskflow-{role}-{tab}.png'),full_page=True)
  for width in (375,768):
   page.set_viewport_size({'width':width,'height':900})
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Workspace overflow {role} {width}'
   page.screenshot(path=str(artifacts/f'taskflow-{role}-{width}.png'),full_page=True)
  page.set_viewport_size({'width':1440,'height':1000})
 print('Browser checks completed. Errors:',json.dumps(errors,ensure_ascii=False))
 assert not errors
 b.close()
