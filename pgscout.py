import logging
import time
from Queue import Queue
from threading import Thread

from flask import Flask, request, jsonify

from pgscout.Scout import Scout
from pgscout.ScoutJob import ScoutJob
from pgscout.cache import get_cached_encounter, cache_encounter, cleanup_cache
from pgscout.config import cfg_get
from pgscout.console import print_status
from pgscout.utils import get_pokemon_name

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(threadName)16s][%(module)14s][%(levelname)8s] %(message)s')

log = logging.getLogger(__name__)

# Silence some loggers
logging.getLogger('pgoapi.pgoapi').setLevel(logging.WARNING)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__, static_folder='icons', static_url_path='')

scouts = []
jobs = Queue()

# ===========================================================================


@app.route("/iv", methods=['GET'])
def get_iv():
    pokemon_id = request.args["pokemon_id"]
    pokemon_name = get_pokemon_name(pokemon_id)
    lat = request.args["latitude"]
    lng = request.args["longitude"]

    encounter_id = request.args.get("encounter_id")
    spawn_point_id = request.args.get("spawn_point_id")

    # Check cache
    cache_key = encounter_id if encounter_id else "{}-{}-{}".format(pokemon_id, lat, lng)
    result = get_cached_encounter(cache_key)
    if result:
        log.info(
            u"Returning cached result: {:.1f}% level {} {} with {} CP".format(result['iv_percent'], result['level'], pokemon_name, result['cp']))
        return jsonify(result)

    # Create a ScoutJob
    job = ScoutJob(pokemon_id, encounter_id, spawn_point_id, lat, lng)

    # Enqueue and wait for job to be processed
    jobs.put(job)
    while not job.processed:
        time.sleep(1)

    # Cache successful jobs and return result
    if job.result['success']:
        cache_encounter(cache_key, job.result)
    return jsonify(job.result)


def run_webserver():
    app.run(threaded=True, port=cfg_get('port'))


def cache_cleanup_thread():
    while True:
        time.sleep(60)
        num_deleted = cleanup_cache()
        log.info("Cleaned up {} entries from encounter cache.".format(num_deleted))

# ===========================================================================

log.info("PGScout starting up.")

with open(cfg_get('accounts_file'), 'r') as f:
    for num, line in enumerate(f, 1):
        fields = line.split(",")
        fields = map(str.strip, fields)
        scout = Scout(fields[0], fields[1], fields[2], jobs)
        scouts.append(scout)
        t = Thread(target=scout.run, name="{}".format(scout.username))
        t.daemon = True
        t.start()

# Cleanup cache in background
t = Thread(target=cache_cleanup_thread, name="cache_cleaner")
t.daemon = True
t.start()

# Start thread to print current status and get user input.
t = Thread(target=print_status,
           name='status_printer', args=(scouts, 'logs', jobs))
t.daemon = True
t.start()

# Launch the webserver
t = Thread(target=run_webserver, name='webserver')
t.daemon = True
t.start()

# Dummy endless loop.
while True:
    time.sleep(1)