"""Installed-wheel CLI/resources/TUI smoke in a disposable private environment."""
import asyncio,json,os,subprocess,sys
from pathlib import Path
base=Path(sys.argv[1]);project=base/'workspace';project.mkdir(exist_ok=True)
os.chdir(project)
for key in tuple(os.environ):
    if any(part in key.upper() for part in ('API_KEY','ACCESS_TOKEN','AUTH_TOKEN')):os.environ.pop(key,None)
os.environ.update(ISYCODE_STATE_HOME=str(base/'state'),XDG_CONFIG_HOME=str(base/'config'),XDG_STATE_HOME=str(base/'legacy-state'),ISYCO_ROOT=str(base/'stand-in'))
Path(os.environ['ISYCO_ROOT']).mkdir(exist_ok=True)
import isycode
assert Path(isycode.__file__).is_relative_to(base/'venv'),isycode.__file__
from isycode.skill_catalog import skills,read_skill
assert len(skills())>=6 and all(read_skill(name).strip() for name in skills())
exe=base/'venv/Scripts/isycode.exe'
for args in (['--version'],['--help'],['doctor','--json'],['dirs','--json']):
 result=subprocess.run([str(exe),*args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
 assert result.returncode==0,(args,result.stderr[:400])
 print('installed CLI:',args,'exit',result.returncode)
from isycode.tui import TUIApp,QuickStartScreen,WorkspaceSetupScreen,WorkspaceModeScreen,PromptArea
async def scenario():
 app=TUIApp()
 async with app.run_test(size=(120,40)) as pilot:
  await pilot.pause();assert isinstance(app.screen,QuickStartScreen)
  await pilot.press('escape');await pilot.pause();assert isinstance(app.screen,WorkspaceSetupScreen)
  await pilot.press('escape');await pilot.pause();assert isinstance(app.screen,WorkspaceModeScreen)
  await pilot.press('escape');await pilot.pause()
  prompt=app.query_one('#prompt-input',PromptArea)
  assert app.focused is prompt and prompt.text==''
  await pilot.press('f6');await pilot.pause();assert app.query_one('#files-view').display
  await pilot.press('shift+f6');await pilot.pause();assert app.query_one('#overview-view').display
asyncio.run(scenario())
print('installed wheel: catalog integrity, private onboarding and headless TUI PASS')
