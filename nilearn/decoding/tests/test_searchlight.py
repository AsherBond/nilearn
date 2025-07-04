"""Test the searchlight module."""

import numpy as np
import pytest
from nibabel import Nifti1Image
from sklearn.model_selection import (
    KFold,
    LeaveOneGroupOut,
)
from sklearn.utils.estimator_checks import parametrize_with_checks

from nilearn._utils.estimator_checks import (
    check_estimator,
    nilearn_check_estimator,
    return_expected_failed_checks,
)
from nilearn._utils.tags import SKLEARN_LT_1_6
from nilearn.conftest import _rng
from nilearn.decoding import searchlight

ESTIMATOR_TO_CHECK = [searchlight.SearchLight()]

if SKLEARN_LT_1_6:

    @pytest.mark.parametrize(
        "estimator, check, name",
        check_estimator(estimators=ESTIMATOR_TO_CHECK),
    )
    def test_check_estimator_sklearn_valid(estimator, check, name):  # noqa: ARG001
        """Check compliance with sklearn estimators."""
        check(estimator)

    @pytest.mark.xfail(reason="invalid checks should fail")
    @pytest.mark.parametrize(
        "estimator, check, name",
        check_estimator(estimators=ESTIMATOR_TO_CHECK, valid=False),
    )
    def test_check_estimator_sklearn_invalid(estimator, check, name):  # noqa: ARG001
        """Check compliance with sklearn estimators."""
        check(estimator)

else:

    @parametrize_with_checks(
        estimators=ESTIMATOR_TO_CHECK,
        expected_failed_checks=return_expected_failed_checks,
    )
    def test_check_estimator_sklearn(estimator, check):
        """Check compliance with sklearn estimators."""
        check(estimator)


@pytest.mark.parametrize(
    "estimator, check, name",
    nilearn_check_estimator(
        estimators=[
            searchlight.SearchLight(
                mask_img=Nifti1Image(
                    np.ones((5, 5, 5), dtype=bool).astype("uint8"), np.eye(4)
                )
            )
        ]
    ),
)
def test_check_estimator_nilearn(estimator, check, name):  # noqa: ARG001
    """Check compliance with nilearn estimators rules."""
    check(estimator)


def _make_searchlight_test_data(frames):
    data = _rng().random((5, 5, 5, frames))
    mask = np.ones((5, 5, 5), dtype=bool)
    mask_img = Nifti1Image(mask.astype("uint8"), np.eye(4))
    # Create a condition array, with balanced classes
    cond = np.arange(frames, dtype=int) >= (frames // 2)

    data[2, 2, 2, :] = 0
    data[2, 2, 2, cond] = 2
    data_img = Nifti1Image(data, np.eye(4))

    return data_img, cond, mask_img


def define_cross_validation():
    # Define cross validation
    cv = KFold(n_splits=4)
    n_jobs = 1
    return cv, n_jobs


def test_searchlight_no_mask():
    """Check validation type mask."""
    sl = searchlight.SearchLight(mask_img=1)

    frames = 30
    data_img, cond, _ = _make_searchlight_test_data(frames)
    with pytest.raises(
        TypeError,
        match="input should be a NiftiLike object",
    ):
        sl.fit(data_img, y=cond)


def test_searchlight_small_radius():
    frames = 30
    data_img, cond, mask_img = _make_searchlight_test_data(frames)
    cv, n_jobs = define_cross_validation()

    # Small radius : only one pixel is selected
    sl = searchlight.SearchLight(
        mask_img,
        process_mask_img=mask_img,
        radius=0.5,
        n_jobs=n_jobs,
        scoring="accuracy",
        cv=cv,
        verbose=1,
    )
    sl.fit(data_img, y=cond)

    assert np.where(sl.scores_ == 1)[0].size == 1
    assert sl.scores_[2, 2, 2] == 1.0


def test_searchlight_mask_far_from_signal(affine_eye):
    frames = 30
    data_img, cond, mask_img = _make_searchlight_test_data(frames)
    cv, n_jobs = define_cross_validation()

    process_mask = np.zeros((5, 5, 5), dtype=bool)
    process_mask[0, 0, 0] = True
    process_mask_img = Nifti1Image(process_mask.astype("uint8"), affine_eye)
    sl = searchlight.SearchLight(
        mask_img,
        process_mask_img=process_mask_img,
        radius=0.5,
        n_jobs=n_jobs,
        scoring="accuracy",
        cv=cv,
    )
    sl.fit(data_img, y=cond)

    assert np.where(sl.scores_ == 1)[0].size == 0


def test_searchlight_medium_radius():
    frames = 30
    data_img, cond, mask_img = _make_searchlight_test_data(frames)
    cv, n_jobs = define_cross_validation()

    sl = searchlight.SearchLight(
        mask_img,
        process_mask_img=mask_img,
        radius=1,
        n_jobs=n_jobs,
        scoring="accuracy",
        cv=cv,
    )
    sl.fit(data_img, cond)

    assert np.where(sl.scores_ == 1)[0].size == 7
    assert sl.scores_[2, 2, 2] == 1.0
    assert sl.scores_[1, 2, 2] == 1.0
    assert sl.scores_[2, 1, 2] == 1.0
    assert sl.scores_[2, 2, 1] == 1.0
    assert sl.scores_[3, 2, 2] == 1.0
    assert sl.scores_[2, 3, 2] == 1.0
    assert sl.scores_[2, 2, 3] == 1.0


def test_searchlight_large_radius():
    frames = 30
    data_img, cond, mask_img = _make_searchlight_test_data(frames)
    cv, n_jobs = define_cross_validation()

    sl = searchlight.SearchLight(
        mask_img,
        process_mask_img=mask_img,
        radius=2,
        n_jobs=n_jobs,
        scoring="accuracy",
        cv=cv,
    )
    sl.fit(data_img, cond)

    assert np.where(sl.scores_ == 1)[0].size == 33
    assert sl.scores_[2, 2, 2] == 1.0


def test_searchlight_group_cross_validation(rng):
    frames = 30
    data_img, cond, mask_img = _make_searchlight_test_data(frames)
    _, n_jobs = define_cross_validation()

    groups = rng.permutation(np.arange(frames, dtype=int) > (frames // 2))

    sl = searchlight.SearchLight(
        mask_img,
        process_mask_img=mask_img,
        radius=1,
        n_jobs=n_jobs,
        scoring="accuracy",
        cv=LeaveOneGroupOut(),
    )
    sl.fit(data_img, y=cond, groups=groups)

    assert np.where(sl.scores_ == 1)[0].size == 7
    assert sl.scores_[2, 2, 2] == 1.0


def test_searchlight_group_cross_validation_with_extra_group_variable(
    rng,
    affine_eye,
):
    frames = 30
    data_img, cond, mask_img = _make_searchlight_test_data(frames)
    cv, n_jobs = define_cross_validation()

    groups = rng.permutation(np.arange(frames, dtype=int) > (frames // 2))

    sl = searchlight.SearchLight(
        mask_img,
        process_mask_img=mask_img,
        radius=1,
        n_jobs=n_jobs,
        scoring="accuracy",
        cv=cv,
    )
    sl.fit(data_img, y=cond, groups=groups)

    assert np.where(sl.scores_ == 1)[0].size == 7
    assert sl.scores_[2, 2, 2] == 1.0

    # Check whether searchlight works on list of 3D images
    data = rng.random((5, 5, 5))
    data_img = Nifti1Image(data, affine=affine_eye)
    imgs = [data_img] * 12

    # labels
    y = [0, 1] * 6

    # run searchlight on list of 3D images
    sl = searchlight.SearchLight(mask_img)
    sl.fit(imgs, y)


def test_mask_img_dimension_mismatch():
    """Test if SearchLight handles mismatched mask and
    image dimensions gracefully.
    """
    data_img, cond, _ = _make_searchlight_test_data(frames=20)

    # Create a mask with smaller dimensions (4x4x4 vs 5x5x5 in data_img)
    invalid_mask_img = Nifti1Image(
        np.ones((4, 4, 4), dtype="uint8"), np.eye(4)
    )

    # Instantiate SearchLight with mismatched mask
    sl = searchlight.SearchLight(invalid_mask_img, radius=1.0)

    # Fit should complete without raising an error
    sl.fit(data_img, y=cond)

    # Ensure scores_ exists and is the correct shape
    assert sl.scores_ is not None
    assert sl.scores_.shape == invalid_mask_img.shape


def test_transform_applies_mask_correctly():
    """Test if `transform()` applies the mask correctly."""
    frames = 20
    data_img, cond, mask_img = _make_searchlight_test_data(frames)

    sl = searchlight.SearchLight(mask_img, radius=1.0)
    sl.fit(data_img, y=cond)

    # Ensure model is fitted correctly
    assert sl.scores_ is not None
    assert sl.process_mask_ is not None

    # Perform transform on the same data
    transformed_scores = sl.transform(data_img)

    assert transformed_scores is not None
    assert transformed_scores.shape == (5, 5, 5)
    assert transformed_scores.size > 0


def test_process_mask_shape_mismatch():
    """Test SearchLight with mismatched process mask and image dimensions."""
    frames = 20
    data_img, cond, mask_img = _make_searchlight_test_data(frames)

    # Create a process mask with smaller dimensions
    # (4x4x4 vs 5x5x5 in data_img)
    process_mask_img = Nifti1Image(
        np.ones((4, 4, 4), dtype="uint8"), np.eye(4)
    )

    # Instantiate SearchLight with mismatched process mask
    sl = searchlight.SearchLight(
        mask_img=mask_img, process_mask_img=process_mask_img, radius=1.0
    )

    # Fit should complete without error, but scores may be partially populated
    sl.fit(data_img, y=cond)

    # Ensure scores_ exists and is the correct shape
    assert sl.scores_ is not None
    assert sl.scores_.shape == process_mask_img.shape
