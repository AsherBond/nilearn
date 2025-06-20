"""Generate HTML reports."""

import uuid
import warnings
from string import Template

import pandas as pd

from nilearn._utils.helpers import is_matplotlib_installed
from nilearn._utils.html_document import HTMLDocument
from nilearn._utils.logger import find_stack_level
from nilearn._version import __version__
from nilearn.externals import tempita
from nilearn.maskers import NiftiSpheresMasker
from nilearn.reporting._utils import (
    dataframe_to_html,
    model_attributes_to_dataframe,
)
from nilearn.reporting.utils import (
    CSS_PATH,
    HTML_PARTIALS_PATH,
    HTML_TEMPLATE_PATH,
    JS_PATH,
    figure_to_svg_base64,
)

ESTIMATOR_TEMPLATES = {
    "NiftiLabelsMasker": "report_body_template_niftilabelsmasker.html",
    "MultiNiftiLabelsMasker": "report_body_template_niftilabelsmasker.html",
    "NiftiMapsMasker": "report_body_template_niftimapsmasker.html",
    "MultiNiftiMapsMasker": "report_body_template_niftimapsmasker.html",
    "NiftiSpheresMasker": "report_body_template_niftispheresmasker.html",
    "SurfaceMasker": "report_body_template_surfacemasker.html",
    "SurfaceLabelsMasker": "report_body_template_surfacemasker.html",
    "SurfaceMapsMasker": "report_body_template_surfacemapsmasker.html",
    "default": "report_body_template.html",
}


def _get_estimator_template(estimator):
    """Return the HTML template to use for a given estimator \
    if a specific template was defined in ESTIMATOR_TEMPLATES, \
    otherwise return the default template.

    Parameters
    ----------
    estimator : object instance of BaseEstimator
        The object we wish to retrieve template of.

    Returns
    -------
    template : str
        Name of the template file to use.

    """
    if estimator.__class__.__name__ in ESTIMATOR_TEMPLATES:
        return ESTIMATOR_TEMPLATES[estimator.__class__.__name__]
    else:
        return ESTIMATOR_TEMPLATES["default"]


def embed_img(display):
    """Embed an image or just return its instance if already embedded.

    Parameters
    ----------
    display : obj
        A Nilearn plotting object to display.

    Returns
    -------
    embed : str
        Binary image string.

    """
    if display is None:  # no image to display
        return None
    # If already embedded, simply return as is
    if isinstance(display, str):
        return display
    return figure_to_svg_base64(display.frame_axes.figure)


def _update_template(
    title,
    docstring,
    content,
    overlay,
    parameters,
    data,
    summary_html=None,
    template_name=None,
    warning_messages=None,
):
    """Populate a report with content.

    Parameters
    ----------
    title : str
        The title for the report.

    docstring : str
        The introductory docstring for the reported object.

    content : img
        The content to display.

    overlay : img
        Overlaid content, to appear on hover.

    parameters : dict
        A dictionary of object parameters and their values.

    data : dict
        A dictionary holding the data to be added to the report.
        The keys must match exactly the ones used in the template.
        The default template accepts the following:
            - description (str) : Description of the content.
            - warning_message (str) : An optional warning
              message to be displayed in red. This is used
              for example when no image was provided to the
              estimator when fitting.
        The NiftiLabelsMasker template accepts the additional
        fields:
            - summary (dict) : A summary description of the
              region labels and sizes. This will be displayed
              as an expandable table in the report.

    summary_html : dict if estimator is Surface masker str otherwise, optional
        Summary of the region labels and sizes converted to html table.

    template_name : str, optional
        The name of the template to use. If not provided, the
        default template `report_body_template.html` will be
        used.

    Returns
    -------
    report : HTMLReport
        An instance of a populated HTML report.

    """
    if template_name is None:
        body_template_name = "report_body_template.html"
    else:
        body_template_name = template_name
    body_template_path = HTML_TEMPLATE_PATH / body_template_name
    if not body_template_path.exists():
        raise FileNotFoundError(f"No template {body_template_path}")
    tpl = tempita.HTMLTemplate.from_filename(
        str(body_template_path), encoding="utf-8"
    )

    with (JS_PATH / "carousel.js").open(encoding="utf-8") as js_file:
        js_carousel = js_file.read()

    css_file_path = CSS_PATH / "masker_report.css"
    with css_file_path.open(encoding="utf-8") as css_file:
        css = css_file.read()

    if "n_elements" not in data:
        data["n_elements"] = 0
    if "coverage" in data:
        data["coverage"] = f"{data['coverage']:0.1f}"
    else:
        data["coverage"] = ""

    body = tpl.substitute(
        title=title,
        content=content,
        overlay=overlay,
        docstring=docstring,
        parameters=parameters,
        figure=(
            _insert_figure_partial(
                data["engine"],
                content,
                data["displayed_maps"],
                data["unique_id"],
            )
            if "engine" in data
            else None
        ),
        **data,
        css=css,
        js_carousel=js_carousel,
        warning_messages=_render_warnings_partial(warning_messages),
        summary_html=summary_html,
    )

    # revert HTML safe substitutions in CSS sections
    body = body.replace(".pure-g &gt; div", ".pure-g > div")

    head_template_name = "report_head_template.html"
    head_template_path = HTML_TEMPLATE_PATH / head_template_name
    with head_template_path.open() as head_file:
        head_tpl = Template(head_file.read())

    head_css_file_path = CSS_PATH / "head.css"
    with head_css_file_path.open(encoding="utf-8") as head_css_file:
        head_css = head_css_file.read()

    return HTMLReport(
        body=body,
        head_tpl=head_tpl,
        head_values={
            "head_css": head_css,
            "version": __version__,
            "page_title": f"{title} report",
            "display_footer": "style='display: none'" if is_notebook() else "",
        },
    )


def _define_overlay(estimator):
    """Determine whether an overlay was provided and \
    update the report text as appropriate.
    """
    displays = estimator._reporting()

    if len(displays) == 1:  # set overlay to None
        return None, displays[0]

    elif isinstance(estimator, NiftiSpheresMasker):
        return None, displays

    elif len(displays) == 2:
        return displays[0], displays[1]

    return None, displays


def generate_report(estimator):
    """Generate a report for Nilearn objects.

    Reports are useful to visualize steps in a processing pipeline.
    Example use case: visualize the overlap of a mask and reference image
    in NiftiMasker.

    Parameters
    ----------
    estimator : Object instance of BaseEstimator.
        Object for which the report should be generated.

    Returns
    -------
    report : HTMLReport

    """
    if not is_matplotlib_installed():
        with warnings.catch_warnings():
            mpl_unavail_msg = (
                "Matplotlib is not imported! No reports will be generated."
            )
            warnings.filterwarnings("always", message=mpl_unavail_msg)
            warnings.warn(
                category=ImportWarning,
                message=mpl_unavail_msg,
                stacklevel=find_stack_level(),
            )
            return [None]

    if hasattr(estimator, "_report_content"):
        data = estimator._report_content
    else:
        data = {}

    warning_messages = []

    if estimator.reports is False:
        warning_messages.append(
            "\nReport generation not enabled!\nNo visual outputs created."
        )

    if (
        not hasattr(estimator, "_reporting_data")
        or not estimator._reporting_data
    ):
        warning_messages.append(
            "\nThis report was not generated.\n"
            "Make sure to run `fit` before inspecting reports."
        )

    if warning_messages:
        for msg in warning_messages:
            warnings.warn(
                msg,
                stacklevel=find_stack_level(),
            )

        return _update_template(
            title="Empty Report",
            docstring="Empty Report",
            content=embed_img(None),
            overlay=None,
            parameters={},
            data=data,
            warning_messages=warning_messages,
        )

    return _create_report(estimator, data)


def _insert_figure_partial(engine, content, displayed_maps, unique_id=None):
    tpl = tempita.HTMLTemplate.from_filename(
        str(HTML_PARTIALS_PATH / "figure.html"), encoding="utf-8"
    )
    if not isinstance(content, list):
        content = [content]
    return tpl.substitute(
        engine=engine,
        content=content,
        displayed_maps=displayed_maps,
        unique_id=unique_id,
    )


def _render_warnings_partial(warning_messages):
    if not warning_messages:
        return ""
    tpl = tempita.HTMLTemplate.from_filename(
        str(HTML_PARTIALS_PATH / "warnings.html"), encoding="utf-8"
    )
    return tpl.substitute(warning_messages=warning_messages)


def _create_report(estimator, data):
    html_template = _get_estimator_template(estimator)

    # note that some surface images are passed via data
    # for surface maps masker
    overlay, image = _define_overlay(estimator)
    embeded_images = (
        [embed_img(i) for i in image]
        if isinstance(image, list)
        else embed_img(image)
    )

    summary_html = None
    # only convert summary to html table if summary exists
    if "summary" in data and data["summary"] is not None:
        # convert region summary to html table
        # for Surface maskers create a table for each part
        if "Surface" in estimator.__class__.__name__:
            summary_html = {}
            for part in data["summary"]:
                summary_html[part] = pd.DataFrame.from_dict(
                    data["summary"][part]
                )
                summary_html[part] = dataframe_to_html(
                    summary_html[part],
                    precision=2,
                    header=True,
                    index=False,
                    sparsify=False,
                )
        # otherwise we just have one table
        elif "Nifti" in estimator.__class__.__name__:
            summary_html = pd.DataFrame.from_dict(data["summary"])
            summary_html = dataframe_to_html(
                summary_html,
                precision=2,
                header=True,
                index=False,
                sparsify=False,
            )
    parameters = model_attributes_to_dataframe(estimator)
    with pd.option_context("display.max_colwidth", 100):
        parameters = dataframe_to_html(
            parameters,
            precision=2,
            header=True,
            sparsify=False,
        )
    docstring = estimator.__doc__
    snippet = docstring.partition("Parameters\n    ----------\n")[0]

    # Generate a unique ID for this report
    unique_id = str(uuid.uuid4()).replace("-", "")

    return _update_template(
        title=estimator.__class__.__name__,
        docstring=snippet,
        content=embeded_images,
        overlay=embed_img(overlay),
        parameters=parameters,
        data={**data, "unique_id": unique_id},
        template_name=html_template,
        summary_html=summary_html,
    )


def is_notebook() -> bool:
    """Detect if we are running in a notebook.

    From https://stackoverflow.com/questions/15411967/how-can-i-check-if-code-is-executed-in-the-ipython-notebook
    """
    try:
        shell = get_ipython().__class__.__name__  # type: ignore[name-defined]
        return shell == "ZMQInteractiveShell"
    except NameError:
        return False  # Probably standard Python interpreter


class HTMLReport(HTMLDocument):
    """A report written as HTML.

    Methods such as ``save_as_html``, or ``open_in_browser``
    are inherited from class ``nilearn.plotting.html_document.HTMLDocument``.

    Parameters
    ----------
    head_tpl : Template
        This is meant for display as a full page, eg writing on disk.
        This is the Template object used to generate the HTML head
        section of the report. The template should be filled with:

            - title: The title of the HTML page.
            - body: The full body of the HTML page. Provided through
                the ``body`` input.

    body : :obj:`str`
        This parameter is used for embedding in the provided
        ``head_tpl`` template. It contains the full body of the
        HTML page.

    head_values : :obj:`dict`, default=None
        Additional substitutions in ``head_tpl``.
        if ``None`` is passed, defaults to ``{}``

        .. note::
            This can be used to provide additional values
            with custom templates.

    """

    def __init__(self, head_tpl, body, head_values=None):
        """Construct the ``HTMLReport`` class."""
        if head_values is None:
            head_values = {}
        html = head_tpl.safe_substitute(body=body, **head_values)
        super().__init__(html)
        self.head_tpl = head_tpl
        self.body = body

    def _repr_html_(self):
        """Return body of the report.

        Method used by the Jupyter notebook.
        Users normally won't call this method explicitly.
        """
        return self.body

    def __str__(self):
        return self.body
