"""Optional browser regression checks. Run against a disposable demo database."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument('--app-url', default='http://127.0.0.1:8774')
parser.add_argument('--artifacts-dir', default='/tmp/gangxiang-ui-artifacts')
args = parser.parse_args()
artifacts = Path(args.artifacts_dir)
artifacts.mkdir(parents=True, exist_ok=True)
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(args.app_url, wait_until='networkidle')
    page.locator('#entry-title').wait_for()
    assert '共序·港乡' in page.title()
    assert page.locator('input[type=password], #authForm').count() == 0
    for stage, title in enumerate(('说出需求', '完善方案', '共同确认', '有序交付')):
        page.locator(f'[data-entry-stage="{stage}"]').click()
        assert page.locator('#entry-stage-title').inner_text() == title
    for width in (375, 768, 1440):
        page.set_viewport_size({'width': width, 'height': 900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Opening overflow {width}'
        page.screenshot(path=str(artifacts / f'opening-{width}.png'), full_page=True)
    page.get_by_role('button', name='看看四方如何协作').click()
    frame = page.frame_locator('#story-scene iframe')
    frame.get_by_role('button', name='播放协作构建').click()
    frame.locator('swarm-rebuild').wait_for(state='attached')
    assert frame.locator('swarm-rebuild').evaluate('(e) => getComputedStyle(e).filter') == 'grayscale(1)'
    page.get_by_role('button', name='关闭演示').click()
    page.locator('#story-scene iframe').wait_for(state='detached')
    assert page.evaluate('document.activeElement.hasAttribute("data-open-story")')
    page.emulate_media(reduced_motion='reduce')
    page.get_by_role('button', name='看看四方如何协作').click()
    frame = page.frame_locator('#story-scene iframe')
    frame.get_by_role('heading').first.wait_for()
    assert frame.locator('#play').is_hidden()
    page.keyboard.press('Escape')
    assert not page.locator('dialog').is_visible()
    page.emulate_media(reduced_motion='no-preference')
    # Owner can be selected first: coordinator bootstrap remains invisible.
    page.locator('[data-entry-role=owner]').click()
    page.locator('.enter-product').click()
    page.locator('.sidebar').wait_for()
    assert '住户' in page.locator('.sidebar-footer').inner_text()
    project_id = page.locator('#projectSelect').input_value()
    for role in ('coordinator', 'designer', 'contractor', 'owner'):
        page.locator('.demo-switch summary').click()
        page.locator(f'.demo-switch [data-demo-role={role}]').click()
        page.wait_for_function('(role) => state.user?.role === role && !state.switching', arg=role)
        assert page.locator('#projectSelect').input_value() == project_id
        for tab in ('overview', 'schedule', 'changes', 'tasks', 'members', 'activity'):
            page.locator(f'.nav [data-tab={tab}]').click()
            assert page.locator('.content').inner_text().strip()
            for width in (375, 768, 1440):
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow {role} {tab} {width}'
            if role == 'coordinator' and tab == 'overview':
                page.screenshot(path=str(artifacts / 'workspace-1440.png'), full_page=True)
            if tab == 'tasks' and role == 'contractor':
                page.screenshot(path=str(artifacts / 'tasks-1440.png'), full_page=True)
    page.reload(wait_until='networkidle')
    page.locator('.sidebar').wait_for()
    assert '住户' in page.locator('.sidebar-footer').inner_text()
    assert page.locator('#projectSelect').input_value() == project_id
    page.get_by_role('button', name='返回开场').click()
    page.locator('.opening-layout').wait_for()
    page.get_by_role('button', name='跳过开场，直接进入').click()
    page.locator('.sidebar').wait_for()
    assert page.locator('#projectSelect').input_value() == project_id
    # Fresh browser starts at its own opening and cannot see this browser's project.
    other = browser.new_context()
    outsider = other.new_page()
    outsider.goto(args.app_url, wait_until='networkidle')
    outsider.locator('.opening-layout').wait_for()
    outsider.locator('.enter-product').click()
    outsider.locator('.sidebar').wait_for()
    assert outsider.locator('#projectSelect').input_value() != project_id
    other.close()
    print('Direct entry, 4 roles, 6 tabs, responsive layouts, motion, reload and browser isolation passed.')
    print('Browser errors:', json.dumps(errors, ensure_ascii=False))
    assert not errors
    browser.close()
