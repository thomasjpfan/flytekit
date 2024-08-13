import os
from functools import partial
from typing import Callable, Union

from flytekit import Secret
from flytekit.core.context_manager import FlyteContextManager
from flytekit.core.utils import ClassDecorator

NEPTUNE_RUN_VALUE = "neptune-run-id"


def neptune_init_run(
    project: str,
    secret: Union[Secret, Callable],
    host: str = "https://app.neptune.ai",
    **init_run_kwargs: dict,
):
    return partial(
        _neptune_init_run_class,
        project=project,
        secret=secret,
        host=host,
        **init_run_kwargs,
    )


class _neptune_init_run_class(ClassDecorator):
    NEPTUNE_HOST_KEY = "host"
    NEPTUNE_PROJECT_KEY = "project"

    def __init__(
        self,
        task_function: Callable,
        project: str,
        secret: Union[Secret, Callable],
        host: str = "https://app.neptune.ai",
        **init_run_kwargs: dict,
    ):
        """Neptune plugin."""
        self.project = project
        self.secret = secret
        self.host = host
        self.init_run_kwargs = init_run_kwargs

        super().__init__(task_function, project=project, secret=secret, host=host, **init_run_kwargs)

    def execute(self, *args, **kwargs):
        ctx = FlyteContextManager.current_context()
        is_local_execution = ctx.execution_state.is_local_execution()

        init_run_kwargs = {"project": self.project, **self.init_run_kwargs}

        if not is_local_execution:
            if isinstance(self.secret, Secret):
                secrets = ctx.user_space_params.secrets
                neptune_api_token = secrets.get(key=self.secret.key, group=self.secret.group)
            else:
                # Callable
                neptune_api_token = self.secret()
            init_run_kwargs["api_token"] = neptune_api_token

        import neptune

        run = neptune.init_run(**init_run_kwargs)

        if not is_local_execution:
            # The HOSTNAME is set to {.executionName}-{.nodeID}-{.taskRetryAttempt}
            # If HOSTNAME is not defined, use the execution name as a fallback
            hostname = os.environ.get("HOSTNAME", ctx.user_space_params.execution_id.name)
            run["Flyte Execution ID"] = hostname

            if execution_url := os.getenv("FLYTE_EXECUTION_URL") is not None:
                run["Flyte Execution URL"] = execution_url

        ctx = FlyteContextManager.current_context()
        new_user_params = ctx.user_space_params.builder().add_attr("NEPTUNE_RUN", run).build()

        with FlyteContextManager.with_context(
            ctx.with_execution_state(ctx.execution_state.with_params(user_space_params=new_user_params))
        ):
            output = self.task_function(*args, **kwargs)
            run.stop()
            return output

    def get_extra_config(self):
        return {
            self.NEPTUNE_HOST_KEY: self.host,
            self.NEPTUNE_PROJECT_KEY: self.project,
            self.LINK_TYPE_KEY: NEPTUNE_RUN_VALUE,
        }
