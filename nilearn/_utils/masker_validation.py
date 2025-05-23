import warnings
from collections.abc import Iterable
from string import Template

import numpy as np

from nilearn._utils.logger import find_stack_level
from nilearn.surface import SurfaceImage
from nilearn.typing import NiimgLike

from .cache_mixin import check_memory
from .class_inspect import get_params


def check_embedded_masker(estimator, masker_type="multi_nii", ignore=None):
    """Create a masker from instance parameters.

    Base function for using a masker within a BaseEstimator class

    This creates a masker from instance parameters :

    - If instance contains a mask image in mask parameter,
    we use this image as new masker mask_img, forwarding instance parameters to
    new masker : smoothing_fwhm, standardize, detrend, low_pass= high_pass,
    t_r, target_affine, target_shape, mask_strategy, mask_args...

    - If instance contains a masker in mask parameter, we use a copy of
    this masker, overriding all instance masker related parameters.
    In all case, we forward system parameters of instance to new masker :
    memory, memory_level, verbose, n_jobs

    Parameters
    ----------
    instance : object, instance of BaseEstimator
        The object that gives us the values of the parameters

    masker_type : {"multi_nii", "nii", "surface"}, default="mutli_nii"
        Indicates whether to return a MultiNiftiMasker, NiftiMasker, or a
        SurfaceMasker.

    ignore : None or list of strings
        Names of the parameters of the estimator that should not be
        transferred to the new masker.

    Returns
    -------
    masker : MultiNiftiMasker, NiftiMasker, \
             or :obj:`~nilearn.maskers.SurfaceMasker`
        New masker

    """
    from nilearn.glm.first_level import FirstLevelModel
    from nilearn.glm.second_level import SecondLevelModel
    from nilearn.maskers import MultiNiftiMasker, NiftiMasker, SurfaceMasker

    if masker_type == "surface":
        masker_type = SurfaceMasker
    elif masker_type == "multi_nii":
        masker_type = MultiNiftiMasker
    else:
        masker_type = NiftiMasker

    estimator_params = get_params(masker_type, estimator, ignore=ignore)

    mask = getattr(estimator, "mask", None)
    if isinstance(estimator, (FirstLevelModel, SecondLevelModel)):
        mask = getattr(estimator, "mask_img", None)

    if isinstance(mask, (NiftiMasker, MultiNiftiMasker, SurfaceMasker)):
        # Creating masker from provided masker
        masker_params = get_params(masker_type, mask)
        new_masker_params = masker_params
    else:
        # Creating a masker with parameters extracted from estimator
        new_masker_params = estimator_params
        new_masker_params["mask_img"] = mask
    # Forwarding system parameters of instance to new masker in all case
    if issubclass(masker_type, MultiNiftiMasker) and hasattr(
        estimator, "n_jobs"
    ):
        # For MultiNiftiMasker only
        new_masker_params["n_jobs"] = estimator.n_jobs

    warning_msg = Template(
        "Provided estimator has no $attribute attribute set."
        "Setting $attribute to $default_value by default."
    )

    if hasattr(estimator, "memory"):
        new_masker_params["memory"] = check_memory(estimator.memory)
    else:
        warnings.warn(
            warning_msg.substitute(
                attribute="memory",
                default_value="Memory(location=None)",
            ),
            stacklevel=find_stack_level(),
        )
        new_masker_params["memory"] = check_memory(None)

    if hasattr(estimator, "memory_level"):
        new_masker_params["memory_level"] = max(0, estimator.memory_level - 1)
    else:
        warnings.warn(
            warning_msg.substitute(
                attribute="memory_level", default_value="0"
            ),
            stacklevel=find_stack_level(),
        )
        new_masker_params["memory_level"] = 0

    if hasattr(estimator, "verbose"):
        new_masker_params["verbose"] = estimator.verbose
    else:
        warnings.warn(
            warning_msg.substitute(attribute="verbose", default_value="0"),
            stacklevel=find_stack_level(),
        )
        new_masker_params["verbose"] = 0

    conflicting_param = [
        k
        for k in sorted(estimator_params)
        if np.any(new_masker_params[k] != estimator_params[k])
    ]
    if conflicting_param:
        conflict_string = "".join(
            (
                f"Parameter {k} :\n"
                f"    Masker parameter {new_masker_params[k]}"
                f" - overriding estimator parameter {estimator_params[k]}\n"
            )
            for k in conflicting_param
        )
        warn_str = (
            "Overriding provided-default estimator parameters with"
            f" provided masker parameters :\n{conflict_string}"
        )
        warnings.warn(warn_str, stacklevel=find_stack_level())

    masker = masker_type(**new_masker_params)

    # Forwarding potential attribute of provided masker
    if hasattr(mask, "mask_img_"):
        # Allow free fit of returned mask
        masker.mask_img = mask.mask_img_

    return masker


def check_compatibility_mask_and_images(mask_img, run_imgs):
    """Check that mask type and image types are compatible.

    Images to fit should be a Niimg-Like
    if the mask is a NiftiImage, NiftiMasker or a path.
    Similarly, only SurfaceImages can be fitted
    with a SurfaceImage or a SurfaceMasker as mask.
    """
    from nilearn.maskers import NiftiMasker, SurfaceMasker

    if mask_img is None:
        return None

    if not isinstance(run_imgs, Iterable):
        run_imgs = [run_imgs]

    msg = (
        "Mask and images to fit must be of compatible types.\n"
        f"Got mask of type: {type(mask_img)}, "
        f"and images of type: {[type(x) for x in run_imgs]}"
    )

    volumetric_type = (*NiimgLike, NiftiMasker)
    surface_type = (SurfaceImage, SurfaceMasker)
    all_allowed_types = (*volumetric_type, *surface_type)

    if not isinstance(mask_img, all_allowed_types):
        raise TypeError(
            "\nMask should be of type: "
            f"{[x.__name__ for x in all_allowed_types]}.\n"
            f"Got : '{mask_img.__class__.__name__}'"
        )

    if isinstance(mask_img, volumetric_type) and any(
        not isinstance(x, NiimgLike) for x in run_imgs
    ):
        raise TypeError(
            f"{msg} "
            f"where images should be NiftiImage-like instances "
            f"(Nifti1Image or str or Path)."
        )
    elif isinstance(mask_img, surface_type) and any(
        not isinstance(x, SurfaceImage) for x in run_imgs
    ):
        raise TypeError(
            f"{msg} where SurfaceImage instances would be expected."
        )
