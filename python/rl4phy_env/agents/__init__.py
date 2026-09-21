"""Agents for ``TrackPredictionEnv``, one per file.

Every agent is a plain class with two things: a ``name`` used in the benchmark
table and an ``act(observation) -> (x, y, z)`` method returning the predicted
position of the next hit in mm. There is no base class on purpose. Each file is
meant to be read, and copied, on its own by whoever writes the next agent, so
the little that repeats between them is left repeated.

    random_agent.py       uniform sample from the action box
    persistence_agent.py  the particle does not move between two hits
    drift_agent.py        persistence plus a constant step along z

None of them learns anything. They set the bar a trained model has to clear;
``rl4phy_env.benchmark`` scores them.
"""
