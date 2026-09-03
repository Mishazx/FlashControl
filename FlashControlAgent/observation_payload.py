# -*- coding: utf-8 -*-
"""Pack/unpack Observation batches so shared host context is not repeated."""

from __future__ import print_function


SHARED_OBSERVATION_KEYS = (
    "schema_version",
    "probe_version",
    "host",
    "session",
)


def shared_observation_fields(observations):
    shared = {}
    if not observations:
        return shared
    first = observations[0]
    if not isinstance(first, dict):
        return shared
    for key in SHARED_OBSERVATION_KEYS:
        if key not in first:
            continue
        value = first.get(key)
        if all(
            isinstance(item, dict) and item.get(key) == value
            for item in observations
        ):
            shared[key] = value
    return shared


def expand_observations(document):
    if not isinstance(document, dict):
        raise ValueError("payload must be an object")
    if "observations" not in document:
        return [document]
    values = document.get("observations")
    if values is None:
        values = []
    if not isinstance(values, list):
        raise ValueError("payload must contain an observations list")
    shared = {}
    for key in SHARED_OBSERVATION_KEYS:
        if key in document:
            shared[key] = document[key]
    expanded = []
    for item in values:
        if not isinstance(item, dict):
            raise ValueError("every observation must be an object")
        merged = dict(shared)
        merged.update(item)
        expanded.append(merged)
    return expanded


def pack_observation_payload(observations, extra=None):
    extra = extra or {}
    if not extra and len(observations) == 1:
        return observations[0]
    shared = shared_observation_fields(observations)
    packed = []
    for item in observations:
        copy = dict(item)
        for key in shared:
            copy.pop(key, None)
        packed.append(copy)
    result = dict(shared)
    result.update(extra)
    result["observations"] = packed
    return result
