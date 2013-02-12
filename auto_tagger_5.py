#! /usr/bin/env python
# -*- coding: utf-8 -*-

'''
Title:
    Vanilla Auto-Tagger
Author:
    van@yande.re
Date / Version:
    2013 02 11 / v5
Description:
    Uses the yande.re API, pixiv, danbooru API and iqdb similarity search to
    update the source and artist data of posts on https://yande.re
    Roughly, code does this for all posts satistying initial query:
    - Check for source, artist and circle tags
    - If source is present, but no artist or circle
        - Use "Find artist" on yande.re and danbooru to get artist tag
    - If no source, use iqdb to find similar posts on danbooru
        - If match is good (>90%), check danbooru for source link
        - If source found on danbooru, but no artist or circle on yande.re
            - Use "Find artist" on yande.re and danbooru to get artist tag
    Script checks that artist tags from danbooru exist on yande.re before adding
    Script will also replace pixiv sources that contain 'member_illust' with the
    direct link to the full-sized image
Requires:
    A config file named 'config.cfg' in the same directory as this script.
    Edit the provided config.cfg with your username and password info for your
    accounts on yande.re, pixiv and danbooru.
    Logging in is required for making changes on yande.re, for seeing R-18 posts
    on pixiv, and for some xml queries on danbooru.
    It is recommended that you create secondary accounts on the 3 sites solely
    for this script's use, so that your primary account passwords are not
    stored on disk.
Usage:
	$./auto_tagger_5.py <limit> <apply>
Where:
	<limit> = number of posts to auto-tag
	<apply> = True - apply tag and source changes
		      False - do not apply tag and source changes (e.g. for testing)
Example:
    $./auto_tagger_5.py 10 True
'''

__all__= ['Login', 'Data', 'Post']

import urllib
import urllib2
import re
import sys
import ConfigParser
from lxml import etree


class Login:
    
    '''log in to yande.re and pixiv to make changes and see R-18 posts'''
    
    def __init__(self, url, query):
        self.url = url
        self.query = urllib.urlencode(query)
        self.opener = None

    def login(self):
        '''Create opener object and login.'''
        self.opener = urllib2.build_opener(urllib2.HTTPSHandler(),
                                           urllib2.HTTPCookieProcessor())
        urllib2.install_opener(self.opener)
        self.opener.open(self.url, self.query)


class Data:
    
    '''Perform query and parse xml or html result.'''
    
    def __init__(self, opener, type='xml', base='https://yande.re',
                 url='/post.xml', query={'tags': 'limit:25'}, tag='post'):
        self.opener = opener
        self.type = type
        self.url = base + url
        self.query = urllib.urlencode(query)
        self.tag = tag
        self.results = None
        self.response = None
        
    def get_data(self):
        '''Get data with given tag type from base+url+query.'''
        self.response = self.opener.open(self.url, self.query)
        if self.type == 'html':
            parser = etree.HTMLParser()
            tree = etree.parse(self.response, parser)
        else:
            tree = etree.parse(self.response)
        root = tree.getroot()
        self.results = [x for x in root.iter() if x.tag == self.tag]


class Post:
    
    def __init__(self, element, moe_opener, pixiv_opener, dan_opener):
        keys = element.keys()
        values = element.values()
        for i in range(len(keys)):
            setattr(self, keys[i], values[i])
        self.mo = moe_opener
        self.po = pixiv_opener
        self.do = dan_opener
        self.has_artist = False
        self.has_circle = False
        self.has_source = False
        self.complete = False
        self.update_source = False
        self.update_artist = False
    
    def check(self):
        print 'Post', self.id
        self.has()
        if self.has_source and not self.complete:
            self.member()
        if self.has_source and not self.has_artist:
            self.artist()
        if not self.has_source:
            self.iqdb()
            if self.update_source and not self.has_artist:
                self.artist()
        self.update()

    def has(self):
        '''Check if post already has artist, circle, source.'''
        if self.source != '':
            self.has_source = True
            print '    Has source:', self.source
        tags = self.tags.split()
        url = '/tag.xml'
        for tag in tags:
            query = {'name': tag.encode('utf-8'), 'type': '1', 'order': 'count'}
            artists = Data(self.mo, url=url, query=query, tag='tag')
            artists.get_data()
            values = flatten([x.values() for x in artists.results])
            if tag in values:
                self.has_artist = True
                print '    Has artist:', tag
                break
        if self.has_artist == False:
            for tag in tags:
                query = {'name': tag.encode('utf-8'), 'type': '5',
                         'order': 'count'}
                circles = Data(self.mo, url=url, query=query, tag='tag')
                circles.get_data()
                values = flatten([x.values() for x in circles.results])
                if tag in values:
                    self.has_circle = True
                    print '    Has cirlce:', tag
                    break
        if (self.has_source and (self.has_artist or self.has_circle) and
            'member_illust' not in self.source):
            self.complete = True
            print '    Post is complete'

    def member(self):
        '''Check for member_illust pixiv sources and change to proper source.'''
        if 'member_illust' in self.source:
            pixiv = Data(self.po, type='html', base=self.source, url='',
                         query={}, tag='meta')
            pixiv.get_data()
            print '    Opened:', pixiv.url
            source = ''
            for y in pixiv.results:
                if 'og:image' in y.values():
                    source = y.values()[1]
            if source != '' and 'pixiv_logo' not in source:
                self.source = source.replace('_s.', '.')
                self.update_source = True
                print '    Found source on pixiv:', self.source
            if 'pixiv_logo' in source:
                pixiv = Data(self.po, type='html', base=self.source, url='',
                             query={}, tag='span')
                pixiv.get_data()
                values = [x.values() for x in pixiv.results]
                keys = [x.keys() for x in pixiv.results]
                for i in range(len(values)):
                    if values[i][keys[i].index('class')] == 'error':
                        children = pixiv.results[i].getchildren()
                        print '    Pixiv msg:', children[0].text

    def artist(self):
        '''Find artist on imouto and danbooru using "Find artist" service.'''
        url = '/artist.xml'
        query = {'url': self.source.encode('utf-8'), 'limit': '10'}
        artists = Data(self.mo, url=url, query=query, tag='artist')
        artists.get_data()
        values = [x.values() for x in artists.results]
        if len(values) == 1:
            artist = values[0][1]
            self.update_artist = True
            print '    Found artist on yande.re:', artist
            self.tags += ' ' + artist
        if self.update_artist == False:
            base = 'http://danbooru.donmai.us'
            url = '/artist/index.xml'
            query = {'name': self.source.encode('utf-8'), 'limit': '10'}
            artists = Data(self.mo, base=base, url=url, query=query,
                           tag='artist')
            artists.get_data()
            values = [x.values() for x in artists.results]
            keys = [x.keys() for x in artists.results]
            if len(values) == 1:
                artist = values[0][keys[0].index('name')]
                print '    Possible artist from danbooru:', artist
                url = '/artist.xml'
                query = {'name': artist.encode('utf-8'), 'limit': '10'}
                artists = Data(self.mo, url=url, query=query, tag='artist')
                artists.get_data()
                values = [x.values() for x in artists.results]
                if artist in values:
                    self.update_artist = True
                    print '    Artist exists on yande.re:', artist
                    self.tags += ' ' + artist

    def iqdb(self):
        '''
        Check on iqdb for matches on danbooru for current post, update source
        tag if appropriate.
        '''
        base = 'http://danbooru.iqdb.org/'
        query = {'url': self.preview_url}
        iq = Data(self.po, type='html', base=base, url='', query=query,
                  tag='th')
        iq.get_data()
        text = [x.text for x in iq.results]
        if 'Best match' in text:
            index = text.index('Best match')
            tr1 = iq.results[index].getparent()
            tr2 = tr1.getnext()
            td = tr2.getchildren()
            a = td[0].getchildren()
            link = a[0].values()[0]
            id = link.split('/')[-1]
            tr4 = (tr2.getnext()).getnext()
            similarity = int(tr4.getchildren()[0].text.split('%')[0])
            print '    Searching danbooru with iqdb - best similarity:', similarity
            if similarity >= 90:
                base = 'http://danbooru.donmai.us'
                url = '/post/index.xml'
                query = {'tags': 'id:'+id}
                dan = Data(self.do, base=base, url=url, query=query)
                dan.get_data()
                if dan.results != []:
                    values = dan.results[0].values()
                    keys = dan.results[0].keys()
                    source = values[keys.index('source')]
                    crap = ['yande.re', 'oreno', 'kobato', 'kurisu', 'mage board',
                            'moe-ren']
                    if source != '':
                        total = sum([(x in source) for x in crap])
                        if total == 0:
                            self.source = source
                            self.update_source = True
                            print '    Found source on danbooru:', self.source
                        else:
                            print '    Cyclic reference or image board source:', source
                    else:
                        print '    Empty source on danbooru'
                else:
                    print '    Post deleted from danbooru'
        else:
            print '    No match on danbooru'

    def iqdb2(self):
        '''
        Check on iqdb for matches on danbooru for current post, update source
        tag if appropriate. Uses the xml api rather than html.
        '''
        base = 'http://danbooru.iqdb.org'
        url='/index.xml'
        query = {'url': self.preview_url}
        iq = Data(self.po, base=base, url=url, query=query,
                  tag='match')
        iq.get_data()
        values = iq.results[0].values()
        keys = iq.results[0].keys()
        similarity = int(float(values[keys.index('sim')]))
        print '    Searching danbooru with iqdb - best similarity:', similarity
        if similarity >= 90:
            post = iq.results[0].getchildren()[0]
            #values = post.values()
            #keys = post.keys()
            source = post.values()[post.keys().index('source')]
            #source = values[keys.index('source')]
            crap = ['yande.re', 'oreno', 'kobato', 'kurisu', 'mage board',
                    'moe-ren']
            if source != '':
                total = sum([(x in source) for x in crap])
                if total == 0:
                    self.source = source
                    self.update_source = True
                    print '    Found source on danbooru:', self.source
                else:
                    print '    Cyclic reference or image board source:', source
            else:
                print '    Empty source on danbooru'

    def update(self):
        '''Update source and artist tag.'''
        url = '/post/update.xml'
        if APPLY:
            if self.update_source:
                query = {'id': self.id,
                         'post[source]': self.source.encode('utf-8')}
                response = self.mo.open(base+url, urllib.urlencode(query))
                print '    Updating source:', response.code, response.msg
            if self.update_artist:
                query = {'id': self.id, 'post[tags]': self.tags.encode('utf-8')}
                response = self.mo.open(base+url, urllib.urlencode(query))
                print '    Updating tags:', response.code, response.msg


def flatten(a):
    '''Convert list of lists (lol) into one list.'''
    y = []
    for x in a:
        y += x
    return y    


if __name__ == '__main__':
    
    global APPLY

    #Set whether to apply tag and source changes.
    if sys.argv[2] == 'True':
        APPLY = True
    else:
        APPLY = False
    #Number of posts to try to update, starting from most recent.
    limit = sys.argv[1]
    
    base = 'https://yande.re'
    
    #Read user info from config file.
    config = ConfigParser.ConfigParser()
    config.read('config.cfg')
    
    #Specify login parameters.
    moe_url = '/user/authenticate'
    moe_params = {'commit': 'Login', 'url': '',
                  'user[name]': config.get('yandere', 'username'),
                  'user[password]': config.get('yandere', 'password')}
    pixiv_url='http://www.pixiv.net/login.php'
    pixiv_params = {'mode': 'login', 'pixiv_id': config.get('pixiv', 'username'),
                    'pass': config.get('pixiv' ,'password')}
    danbooru_url = 'http://danbooru.donmai.us/user/authenticate'
    danbooru_params = {'commit': 'Login', 'url': '',
                       'user[name]': config.get('danbooru', 'username'),
                       'user[password]': config.get('danbooru', 'password')}
    
    #Create openers.
    l = Login(base + moe_url, moe_params)
    l.login()
    mo = l.opener
    l = Login(pixiv_url, pixiv_params)
    l.login()
    po = l.opener
    l = Login(danbooru_url, danbooru_params)
    l.login()
    do = l.opener

    #Get data from yande.re
    #query = {'tags': 'source:*member_illust* limit:'+limit}
    query = {'tags': 'limit:'+limit}
    m = Data(mo, query=query)
    m.get_data()
    for x in m.results:
        n = Post(x, mo, po, do)
        n.check()
    