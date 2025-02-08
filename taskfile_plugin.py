import logging
import os
import subprocess
from typing import List, TypedDict, cast

import sublime
import sublime_plugin

LocationCacheItem = TypedDict(
    "LocationCacheItem", {"location": str, "timestamp": float}
)


class TaskfileRunTask(sublime_plugin.WindowCommand):
    def __init__(self, window):
        self._logger = logging.getLogger(__name__)
        super().__init__(window)

    def run(self):
        try:
            self.run_internal()
        except Exception as ex:
            self._logger.exception("Error launching task")
            self.write_to_panel(f"Error launching task:\n{str(ex)}")

    def run_internal(self):
        folders = self.window.folders()
        tasks_directory = folders[0] if len(folders) else None

        if tasks_directory is None:
            raise Exception("No directories in project")

        tasks = self.get_tasks(tasks_directory)
        self._logger.info(tasks)

        quick_panel_items = [
            sublime.QuickPanelItem(
                trigger=it["desc"] or it["name"],
                annotation=it["name"],
                details=it["summary"] or it["desc"],
                kind=sublime.KIND_AMBIGUOUS,
            )
            for it in tasks
        ]

        def on_select(selected_idx):
            if selected_idx < 0:
                return

            selected_item: sublime.QuickPanelItem = quick_panel_items[selected_idx]
            task_name = selected_item.annotation

            self._logger.info(quick_panel_items[selected_idx])

            sp = subprocess.Popen(
                ["task", task_name],
                cwd=tasks_directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.DETACHED_PROCESS,
            )

            output, _ = sp.communicate()

            self._logger.info(output)

            self.write_to_panel(output.decode("utf-8"))

        self.window.show_quick_panel(quick_panel_items, on_select=on_select)

    def write_to_panel(self, content: str):
        panel = self.window.find_output_panel("Taskfile")

        if not panel:
            panel = self.window.create_output_panel("Taskfile")

        if content[-1] != "\n":
            content += "\n"

        panel.run_command(
            "append",
            {
                "characters": content,
                "scroll_to_end": True,
                "disable_tab_translation": True,
            },
        )
        self.window.run_command("show_panel", {"panel": "output.Taskfile"})

    def get_tasks(self, tasks_directory: str):
        directory = cast(str | None, self.window.settings().get("taskfile.directory"))
        content = cast(dict | None, self.window.settings().get("taskfile.content"))
        locations = cast(
            List[LocationCacheItem] | None,
            self.window.settings().get("taskfile.locations"),
        )

        if (directory != tasks_directory) or (locations is None) or (content is None):
            self._logger.info("No data configured, updating")
            content = self.update_taskfile_content(tasks_directory)
        elif self.locations_updated(locations):
            self._logger.info("Taskfiles updated")
            content = self.update_taskfile_content(tasks_directory)
        else:
            self._logger.info("Using cached data")

        return content["tasks"]

    def update_taskfile_content(self, tasks_directory: str) -> dict:
        content = self.get_taskfile_content(tasks_directory)
        locations_set = set([it["location"]["taskfile"] for it in content["tasks"]])
        locations_set.add(content["location"])
        locations = list(
            {"location": it, "timestamp": os.stat(it).st_mtime} for it in locations_set
        )

        self.window.settings().set("taskfile.directory", tasks_directory)
        self.window.settings().set("taskfile.content", content)
        self.window.settings().set("taskfile.locations", locations)

        return content

    def get_taskfile_content(self, tasks_directory: str) -> dict:
        ps = subprocess.Popen(
            ["task", "--list-all", "--json"],
            cwd=tasks_directory,
            creationflags=subprocess.DETACHED_PROCESS,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        output, error_output = ps.communicate()

        if ps.returncode != 0:
            raise Exception(error_output.decode("utf-8"))
        return sublime.json.loads(output)

    def locations_updated(self, locations: List[LocationCacheItem]) -> bool:
        for location in locations:
            stat = os.stat(location["location"])
            self._logger.info(
                f"Comparing ({location['location']}): {stat.st_mtime} to {location['timestamp']}"
            )
            if stat.st_mtime > location["timestamp"]:
                return True
        return False
