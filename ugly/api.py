#!/usr/bin/env python
# -*- coding: utf-8 -*-

__all__ = ["api"]

import flask
import requests
import feedfinder
from functools import wraps
from flask.ext.login import current_user

from .database import db
from .models import User, Feed

api = flask.Blueprint("api", __name__)


def _get_user():
    token = flask.request.values.get("token")
    if token is not None:
        return User.query.filter_by(api_token=token).first()
    return current_user


def private_view(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        user = _get_user()

        # Check for invalid API tokens.
        if user is None:
            return flask.jsonify(message="Invalid API token."), 403

        # Check to make sure that the current user is valid.
        if not user.is_authenticated():
            return flask.abort(404)

        return func(*args, **kwargs)
    return decorated_view


@api.route("/")
def index():
    return flask.render_template("api.html")


@api.route("/new")
def new_key():
    if not current_user.is_authenticated():
        return flask.abort(404)
    current_user.api_token = current_user.generate_token()
    db.session.commit()
    return flask.redirect(flask.url_for(".index"))


@api.route("/feeds")
@private_view
def feeds():
    feeds = _get_user().feeds
    return flask.jsonify(
        count=len(feeds),
        feeds=[feed.to_dict() for feed in feeds],
    )


@api.route("/subscribe", methods=["GET", "POST"])
@private_view
def subscribe():
    # Get the requested subscription URL.
    add_url = flask.request.values.get("url")
    if add_url is None:
        return flask.jsonify(message="You must provide a URL."), 400

    # Try to find a feed below the requested resource.
    url = feedfinder.feed(add_url)
    if url is None:
        # One last try.
        r = requests.get(add_url)
        data = r.text
        if (r.status_code != requests.code.ok or data.count("<html") > 0 or
            (data.count("<rss") + data.count("<rdf") + data.count("<feed")
             == 0)):
            return flask.jsonify(message="The robot can't find a feed at that "
                                 "URL. Could you help it with a more specific "
                                 "link?"), 400
        url = add_url

    # See if the user is already subscribed to a feed at that URL.
    user = _get_user()
    feed = db.session.query(Feed).join(User.feeds) \
        .filter(User.id == user.id) \
        .filter(Feed.url == url).first()
    if feed is not None:
        return flask.jsonify(
            message="You've already subscribed to {0}.".format(feed.title),
            feed=feed.to_dict(),
        )

    # See if a feed object already exists for that URL.
    feed = Feed.query.filter(Feed.url == url).first()

    # If it doesn't, create a new one.
    if feed is None:
        feed = Feed(url)

        # Update the feed immediately to get the title, etc.
        feed.update_info()

    # Subscribe the current user.
    user.feeds.append(feed)
    db.session.commit()

    return flask.jsonify(
        message="Successfully subscribed to {0}.".format(feed.title),
        feed=feed.to_dict(),
    )


@api.route("/unsubscribe/<int:feedid>", methods=["GET", "POST"])
@private_view
def unsubscribe(feedid):
    user = _get_user()

    # Find the feed that the user wants to unsubscribe from.
    feed = db.session.query(Feed).join(User.feeds) \
        .filter(User.id == user.id) \
        .filter(Feed.id == feedid).first()

    # If the user isn't subscribed, return a failure.
    if feed is None:
        return flask.jsonify(message="Invalid feed ID."), 400

    # Unsubscribe the user.
    title = feed.title
    user.feeds.remove(feed)
    db.session.commit()

    return flask.jsonify(message="Successfully unsubscribed from {0}."
                         .format(title))
