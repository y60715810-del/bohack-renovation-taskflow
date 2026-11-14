"""Browser regression: original role-based product plus a monochrome opening."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument('--app-url', default='http://127.0.0.1:8774')
parser.add_argument('--artifacts-dir', default='/tmp/gangxiang-original-ui')
args = parser.parse_args()
artifacts = Path(args.artifacts_dir)
artifacts.mkdir(parents=True, exist_ok=True)
root = Path(__file__).resolve().parents[1]
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(args.app_url, wait_until='networkidle')
    page.locator('[data-opening-role=owner]:enabled').wait_for()
    assert '共序·港乡' in page.title()
    assert page.locator('input[type=password], #authForm').count() == 0
    for width in (375, 768, 1440):
        page.set_viewport_size({'width': width, 'height': 900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Opening overflow {width}'
        page.screenshot(path=str(artifacts / f'opening-{width}.png'), full_page=True)
    page.get_by_role('button', name='播放协作开场').click()
    frame = page.frame_locator('#story-scene iframe')
    frame.get_by_role('button', name='播放协作构建').click()
    frame.locator('swarm-rebuild').wait_for(state='attached')
    assert frame.locator('swarm-rebuild').evaluate('(e) => getComputedStyle(e).filter') == 'grayscale(1)'
    page.get_by_role('button', name='关闭演示').click()
    page.locator('#story-scene iframe').wait_for(state='detached')
    assert page.evaluate('document.activeElement.hasAttribute("data-open-story")')
    page.emulate_media(reduced_motion='reduce')
    page.get_by_role('button', name='播放协作开场').click()
    frame = page.frame_locator('#story-scene iframe')
    frame.get_by_role('heading').first.wait_for()
    assert frame.locator('#play').is_hidden()
    page.keyboard.press('Escape')
    assert not page.locator('dialog').is_visible()
    page.emulate_media(reduced_motion='no-preference')
    page.locator('[data-opening-role=owner]').click()
    page.locator('.page-head h1').filter(has_text='我的装修').wait_for()
    assert not page.evaluate('Boolean(state.roadshow)'), 'Default product must not be forced into roadshow mode'
    project_id = page.locator('#projectSelect').input_value()

    def switch(role):
        page.locator('.role-directory summary').click()
        page.locator(f'.role-directory [data-demo-role={role}]').click()
        page.wait_for_function('(role) => state.user?.role === role && !state.switching', arg=role)
        assert page.locator('#projectSelect').input_value() == project_id

    headings = {'coordinator': '成员与邀请', 'designer': '设计确认', 'contractor': '施工确认', 'owner': '我的装修'}
    for role, heading in headings.items():
        switch(role)
        assert page.locator('.page-head h1').inner_text() == heading
        assert page.locator('.nav [data-tab]').count() == 1, 'Original default role navigation changed'
        for width in (375, 768, 1440):
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Role overflow {role} {width}'
        page.screenshot(path=str(artifacts / f'role-{role}.png'), full_page=True)
    # Exercise the original workflow rather than merely checking that pages render.
    page.locator('#newChange textarea').fill('厨房墙砖想换成浅色，客厅照旧。请确认差价和交付日期。')
    page.locator('#newChange button').first.click()
    page.wait_for_function('() => change()?.collaboration?.status === "review"')
    change_id = page.evaluate('state.changeId')
    for role in ('designer', 'contractor', 'owner'):
        switch(role)
        page.locator('#simpleDecision textarea').fill('已核对本版方案、变更范围与交付条件，同意按本版执行。')
        page.locator('#simpleDecision [value=approve]').click()
        expected = {'designer': 'review', 'contractor': 'owner', 'owner': 'active'}[role]
        page.wait_for_function('(expected) => change()?.collaboration?.status === expected && !state.dirty', arg=expected)
        assert page.evaluate('state.changeId') == change_id
    assert '方案已生效' in page.locator('.content').inner_text()
    switch('contractor')
    page.locator('#simplePhoto [name=reference]').fill('厨房墙砖到货，核对包装与规格。')
    page.locator('#simplePhoto [name=file]').set_input_files(str(root / 'demo-assets/01_规格一致_800x800.jpg'))
    before = page.locator('.photo-grid img').count()
    page.locator('#simplePhoto').get_by_role('button', name='上传现场照片', exact=True).click()
    page.wait_for_function('(before) => document.querySelectorAll(".photo-grid img").length > before', arg=before)
    page.screenshot(path=str(artifacts / 'original-photo-flow.png'), full_page=True)
    # Native compact directory supports Escape and preserves page state.
    page.locator('.role-directory summary').click()
    page.screenshot(path=str(artifacts / 'role-directory.png'), full_page=True)
    page.keyboard.press('Escape')
    assert not page.locator('.role-directory').evaluate('(el) => el.open')
    page.locator('.role-directory summary').click()
    page.locator('[data-return-opening]').click()
    page.locator('.opening-main').wait_for()
    page.get_by_role('button', name='跳过开场').click()
    page.locator('.sidebar').wait_for()
    assert page.locator('#projectSelect').input_value() == project_id
    assert page.evaluate('state.changeId') == change_id
    # Explicit original roadshow URL still exposes all six existing pages.
    page.goto(args.app_url.rstrip('/') + '/?show=1', wait_until='networkidle')
    page.locator('[data-skip-opening]:enabled').click()
    assert page.locator('.nav [data-tab]').count() == 6
    for tab in ('overview', 'schedule', 'changes', 'tasks', 'members', 'activity'):
        page.locator(f'.nav [data-tab={tab}]').click()
        assert page.locator('.content').inner_text().strip()
        for width in (375, 768, 1440):
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Advanced overflow {tab} {width}'
    print('Original role pages/routing, three-party approval, photo upload, advanced pages, opening and motion passed.')
    print('Browser errors:', json.dumps(errors, ensure_ascii=False))
    assert not errors
    browser.close()
