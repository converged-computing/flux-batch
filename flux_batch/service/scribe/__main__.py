#!/usr/bin/env python3
import errno
import logging
import os
import sys
import time

import flux
import flux.job

# Not necessary, but it makes it pretty
from rich import print

# Use the synchronous version of the backend to avoid asyncio-in-thread conflicts
from flux_batch.service.scribe.database import SQLAlchemyBackend

# Setup logging to stderr (to avoid polluting stdout if run manually)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", stream=sys.stderr
)
logger = logging.getLogger("flux-scribe")


class JournalScribe:
    def __init__(self, db_url: str):
        """
        Initializes the Scribe with a synchronous DB backend and a Flux Journal Consumer.
        """
        # Setup Database
        logger.info(f"Connecting to Database: {db_url}")
        self.db = SQLAlchemyBackend(db_url)
        self.db.initialize()

        try:
            self.handle = flux.Flux()
            logger.info("Connected to Flux instance.")
        except Exception as e:
            logger.critical(f"Failed to connect to Flux: {e}")
            sys.exit(1)

        # Initialize Journal Consumer
        # This consumes the global event log for the entire instance
        self.consumer = flux.job.JournalConsumer(self.handle)
        self.running = True

    def _normalize_event(self, event) -> dict:
        """
        Converts a Flux event object into the dictionary format expected by record_event.
        Matches the logic provided in your EventsEngine reference.
        """
        # Convert the SWIG/CFFI event object to a dictionary
        payload = dict(event)

        return {
            "id": str(getattr(event, "jobid", "unknown")),
            "type": getattr(event, "name", "unknown"),
            "timestamp": getattr(event, "timestamp", time.time()),
            "payload": payload,
            "R": getattr(event, "R", None),
            "jobspec": getattr(event, "jobspec", None),
        }

    def run(self):
        """
        Main execution loop. Polls the journal and writes to the DB.
        """
        try:
            logger.info("🚀 Flux Scribe (Journal Consumer) started.")
            self.consumer.start()

            while self.running:
                try:
                    # Non-blocking poll (100ms timeout)
                    # This allows the loop to check for shutdown signals regularly
                    event = self.consumer.poll(timeout=0.1)

                    if event:
                        print(event)
                        # We only care about events associated with a job
                        if hasattr(event, "jobid"):
                            clean_event = self._normalize_event(event)
                            self.db.record_event("local", clean_event)
                    else:
                        # If no event, yield a tiny bit of CPU
                        time.sleep(0.01)

                except EnvironmentError as e:
                    # Ignore timeouts (no data)
                    if e.errno == errno.ETIMEDOUT:
                        continue
                    logger.error(f"Flux connection error: {e}")
                    time.sleep(1)

                except Exception as e:
                    logger.error(f"Unexpected error in event loop: {e}")
                    time.sleep(1)

        except Exception as e:
            logger.critical(f"EventsEngine crashed: {e}")
        finally:
            self.db.close()
            logger.info("EventsEngine thread exiting.")


def main():
    # Retrieve DB path from environment or use a default
    db_path = os.environ.get("FLUX_SCRIBE_DATABASE", "sqlite:///server_state.db")
    scribe = JournalScribe(db_path)
    scribe.run()


if __name__ == "__main__":
    main()
