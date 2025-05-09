import base64
import json
import logging
import math
import os
import sys
import time
from datetime import datetime
from enum import Enum

import requests

# Initialize logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SCANNED_FILE_DIR = os.environ.get("REPORT_PATH", "/app/data/")


class Checkmarx:
    def __init__(self, bearer_token, project_name, base_url, main_branch):
        self.project_name = project_name
        self.main_branch = main_branch
        self.bearer_token = bearer_token
        self.base_url = base_url

    MAX_RETRIES = 3  # Maximum retry attempts

    def _fetch_data(self, endpoint):
        log.info(f"<info> Fetching data for endpoint: {endpoint} </info>")

        try:
            url = f"{self.base_url}/{endpoint}"
            headers = {
                "accept": "application/json",
                "Authorization": f"Bearer {self.bearer_token}",
            }

            for attempt in range(self.MAX_RETRIES):
                response = requests.get(url, headers=headers)

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 401:  # Unauthorized
                    if attempt < self.MAX_RETRIES:
                        log.info(
                            f"<warning>Unauthorized access. Retrying... ({attempt + 1}/{self.MAX_RETRIES}) </warning>",
                        )
                        raise RuntimeError("Bearer Token has expired.")

                if response.status_code == 400:
                    log.error(f"<error> Bad request {response.json()} </error> ")

                if response.status_code == 403:
                    log.error(f"<error> Forbidden : {response} </error> ")
                if response.status_code == 404:
                    log.error(f"<error> Resource not found :  {response} </error> ")
                else:
                    log.error(f"<error> Unknow error {response.json()} </error> ")
        except Exception as e:
            log.error(f"<error> {e} </error> ")

    def _fetch_checkmarx_projects(self, project=None):
        """
        Fetch projects from Checkmarx API.
        :return: JSON response containing project data
        """
        log.info(f"<info> Fetch a projects details from Checkmarx </info>")

        limit = 10
        offset = 0
        endpoint = f"projects/?limit={limit}&offset={offset}&names={project}"
        data = self._fetch_data(endpoint)
        filteredTotalCount = data.get("filteredTotalCount")
        if filteredTotalCount:
            log.info("<info> project name is correct </info>")
        if data.get("projects"):
            project_data = data.get("projects")[0]
            return project_data, project_data.get("id")
        else:
            log.error(f"<error> There is no project with name {project}. </error>")
            return {}, None

    def _fetch_scan_id(self, project_id, scan_date):
        log.info(
            f"<info> Fetching latest scan id for project: {project_id} and date: {scan_date}</info>",
        )
        # Convert to RFC 3339 format
        scan_date = scan_date.replace("+00:00", "Z")
        endpoint = f"scans/?statuses=Completed&statuses=Partial&project-id={project_id}&from-date={scan_date}"
        scans = self._fetch_data(endpoint)
        scan_id = []
        scan_detail = []
        for scan in scans.get("scans", []):
            scan_id.append(scan.get("id"))
            scan_detail.append(scan)
        return scan_id, scan_detail

    def _fetch_scan_detail(self, scan_id):
        endpoint = f"scans/{scan_id}"
        scan_detail = self._fetch_data(endpoint)
        return scan_detail

    def _fix_isoformat(self, iso_str):
        if "Z" in iso_str:
            iso_str = iso_str.replace("Z", "+00:00")
        date_part, time_part = iso_str.split("T")
        time_main, offset = time_part.split("+")
        if "." in time_main:
            t, micro = time_main.split(".")
            micro = micro.ljust(6, "0")
            time_main = f"{t}.{micro}"
        return datetime.fromisoformat(f"{date_part}T{time_main}+{offset}")

    def _fetch_last_scan_id(self, project_id, main_branch=False):
        endpoint_completed = f"projects/last-scan?offset=0&limit=20&project-ids={project_id}&use-main-branch={main_branch}&scan-status=Completed"
        scan_completed = self._fetch_data(endpoint_completed)

        endpoint_partial = f"projects/last-scan?offset=0&limit=20&project-ids={project_id}&use-main-branch={main_branch}&scan-status=Partial"
        scan_partial = self._fetch_data(endpoint_partial)
        try:
            # If both are empty, return [], {}
            log.info(
                f"<info> scan_completed: {scan_completed}, scan_partial: {scan_partial}. </info>",
            )
            if not scan_completed and not scan_partial:
                log.info("<info> No completed or partial scans found. </info>")
                return [], []

            key = None

            dt_completed = dt_partial = None

            if scan_completed:
                key = list(scan_completed.keys())[0]
                dt_completed = self._fix_isoformat(scan_completed[key]["createdAt"])

            if scan_partial:
                key = list(scan_partial.keys())[0]
                dt_partial = self._fix_isoformat(scan_partial[key]["createdAt"])

            # Compare timestamps and decide which scan ID to use
            if dt_completed and (not dt_partial or dt_completed > dt_partial):
                log.info("<info> Scan ID from completed scan. </info>")
                scan_id = scan_completed[key]["id"]
            elif dt_partial:
                log.info("<info> Scan ID from partial scan. </info>")
                scan_id = scan_partial[key]["id"]
            else:
                return [], []

            scan_detail = self._fetch_scan_detail(scan_id)
            return [scan_id], [scan_detail]
        except Exception as e:
            log.error(f"<error> {e} </error> ")
            return [], {}

    def _get_result(self, scan_id):
        """
        Fetch all result for a scan_id.
        :return: JSON response containing scan data
        """
        log.info(
            f"<info> Fetching checkmarx scan result for a scan_id:{scan_id} </info>",
        )

        all_result = {}
        all_result["scan_id"] = scan_id
        limit = 1000
        offset = 0
        endpoint = f"results/?limit={limit}&offset={offset}&scan-id={scan_id}"
        data = self._fetch_data(endpoint)
        total_count = data.get("totalCount")
        if total_count is not None:
            all_result["finding"] = data.get("results", [])
            offset = math.ceil(total_count / limit)
        for count in range(1, offset):
            endpoint = f"results/?limit={limit}&offset={count}&scan-id={scan_id}"
            data = self._fetch_data(endpoint)
            if data.get("results"):
                all_result["finding"] += data.get("results", [])

        query_desc = self._get_sast_query_detail(all_result)
        all_result["query_desc"] = query_desc
        return all_result

    def _get_sast_query_detail(self, data):
        query_id = set()
        for item in data.get("finding", []):
            if item.get("type", "") == "sast" and item.get("data", {}).get("queryId"):
                query_id.add(item.get("data", {}).get("queryId"))

        query_description = {}
        count = 0
        paras = ""
        query_id = list(query_id)
        for id in query_id:
            count += 1
            paras += f"ids={id}&"
            if count == 100:
                api = f"queries/descriptions?{paras}"
                query_data = self._fetch_data(api)
                for item in query_data:
                    if item.get("queryId"):
                        query_description[item["queryId"]] = item
                paras = ""
        if query_id:
            api = f"queries/descriptions?{paras}"
            query_data = self._fetch_data(api)
            for item in query_data:
                if item.get("queryId"):
                    query_description[item["queryId"]] = item
        return query_description

    def run(self):
        data, project_id = self._fetch_checkmarx_projects(project=self.project_name)
        if project_id:
            scan_ids, scan_info = self._fetch_last_scan_id(
                project_id,
                main_branch=self.main_branch,
            )
            data["scan"] = scan_info
            scan_result = []
            for scan_id in scan_ids:
                scan_result.append(self._get_result(scan_id))
            data["result"] = scan_result
        # Write results to file
        time_suffix = str(time.time())
        issues_file = os.path.join(SCANNED_FILE_DIR, f"CHECKMARX-CX-{time_suffix}.json")
        with open(issues_file, "w") as f:
            json.dump(data, f, indent=2)


if __name__ == "__main__":
    bearer_token = os.environ.get("BEARER_TOKEN")
    project_name = os.environ.get("PROJECT_NAME")
    base_url = os.environ.get("BASE_URL")
    main_branch = os.environ.get("MAIN_BRANCH", False)
    missing_vars = []
    if not bearer_token:
        missing_vars.append("BEARER_TOKEN")
    if not project_name:
        missing_vars.append("PROJECT_NAME")
    if not base_url:
        missing_vars.append("BASE_URL")

    if missing_vars:
        print(f"❌ Error: Missing required environment variable(s): {', '.join(missing_vars)}", file=sys.stderr)
        sys.exit(1)
    cc = Checkmarx(bearer_token, project_name, base_url, main_branch)
    cc.run()
