#!/usr/bin/env python3
import sys

import pipeline_common
from pipeline_common import ERROR_LOG_FILE, logger

from step1_load_classification import run as run_step1
from step2_enrich_abstract import run as run_step2
from step3_extract_data_links import run as run_step3
from step4_check_downloadable import run as run_step4


def main():
    try:
        print("=== STEP 1 ===")
        run_step1()
        print("=== STEP 2 ===")
        print("Commented because of rate limit")
        # run_step2()
        print("=== STEP 3 ===")
        run_step3()
        print("=== STEP 4 ===")
        run_step4()
        print("=== ALL STEPS DONE ===")
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()
        msg = (
            f"Keyboard interrupt. Last DOI: {pipeline_common.CURRENT_DOI or 'N/A'} "
            f"(error log: {ERROR_LOG_FILE})"
        )
        print(msg, file=sys.stderr)
        logger.error("DOI %s: KeyboardInterrupt", pipeline_common.CURRENT_DOI or "N/A")
        sys.exit(1)


if __name__ == "__main__":
    main()
