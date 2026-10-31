## Common Commands

### Connect to Remote Server
Ctrl+Shift+P Remote-SSH - Connect to Host
Select Kvasir

### Start venv
source .venv/bin/activate

### Run individual test
python -m pytest tests/test_seerr.py -v

### Run test suite
python -m pytest tests/ -v

### Print a particular tool description to ensure it's available/registered
python -c "from planelocket_agent.tools.dispatcher import ToolDispatcher; from planelocket_agent.diagnostics.linux.backend import LinuxDiagnostics; d = ToolDispatcher(LinuxDiagnostics()); print(d.tool_descriptions()['search_media'])"

### test a particular function
python - <<'PY'
from planelocket_agent.config import load_config
from planelocket_agent.tools.dispatcher import ToolDispatcher
from planelocket_agent.diagnostics.linux.backend import LinuxDiagnostics

load_config()

dispatcher = ToolDispatcher(LinuxDiagnostics())

response = dispatcher.execute(
    "get_media_details",
    media_type="movie",
    media_id=286217,
)

movie = response["result"]

print("Title:", movie.get("title"))
print("TMDB ID:", movie.get("id"))
print("Release date:", movie.get("releaseDate"))
print("Media status:", movie.get("mediaInfo"))
PY

### Load new env variables from .env file
python -c "import os; from planelocket_agent.config import load_config; load_config();"

### Live search / call tool
python -c "from planelocket_agent.config import load_config; from planelocket_agent.tools.dispatcher import ToolDispatcher; from planelocket_agent.diagnostics.linux.backend import LinuxDiagnostics; load_config(); d = ToolDispatcher(LinuxDiagnostics()); r = d.execute('search_media', query='The Martian'); print([(x.get('id'), x.get('mediaType'), x.get('title') or x.get('name')) for x in r['result'].get('results', [])[:5]])"


## Add a new integration

- Create an integration file (i.e. src/planelocket_agent/integrations/seerr.py)
- Build relevant functions in that file
- create a test file (i.e. src/test/test_seerr.py)
- add relevant pytests
- update imports in src/planelocket_agent/tools/dispatcher.py
- register new function in src/planelocket_agent/tools/dispatcher.py