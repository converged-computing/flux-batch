from jinja2 import Environment, Undefined


def undefined_template(template):
    """
    Return a template that will render undefined args as they are
    """
    env = Environment(undefined=KeepUndefined)
    return env.from_string(template)


class KeepUndefined(Undefined):
    """
    We need a class that we will run jinja2 templating on twice. The first time,
    we do not want to replace undefined variables with nothing.
    """

    def __str__(self):
        # Returns the raw variable name inside {{ }}
        return f"{{{{ {self._undefined_name} }}}}"
