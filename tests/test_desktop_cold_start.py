import asyncio
from types import SimpleNamespace

from research_y.desktop.app import recover_cold_page


def test_retry_only_reopens_authenticated_home_before_user_activity():
    flags=dict(session_redeemed=True,page_accepted=True,socket_allowed=False)
    session=SimpleNamespace(startup_stages=lambda:dict(flags),origin="http://127.0.0.1:49201")
    state=SimpleNamespace(project=None)
    observed=[]
    class Window:
        async def load_url(self,url):
            observed.append(url)
            flags["socket_allowed"]=True
    asyncio.run(recover_cold_page(Window(),session,state,delay=0))
    assert observed==[session.origin+"/"]
    flags.update(session_redeemed=False,socket_allowed=False)
    asyncio.run(recover_cold_page(Window(),session,state,delay=0))
    flags["session_redeemed"]=True
    state.project=object()
    asyncio.run(recover_cold_page(Window(),session,state,delay=0))
    assert observed==[session.origin+"/"]
