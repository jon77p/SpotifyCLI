#!python3

import configparser
import urllib
import requests
import sys
import os
import subprocess
import webbrowser
import time
import re
from base64 import b64encode
from bs4 import BeautifulSoup
import numpy as np
from PIL import Image
import imgcat
from argparsejson import argparsejson

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

def parse_config():
    config = configparser.ConfigParser()

    config.read(os.path.join(SCRIPT_DIR, 'secrets.conf'))

    if 'Application Configuration' in config:
        app_config = config['Application Configuration']
    else:
        raise Exception('Missing config section!')

    app_token = app_config.get('app token')
    refresh_token = app_config.get('refresh token')

    return {'app_token': app_token, 'refresh_token': refresh_token}

def getScopes():
    print('Retrieving valid scopes from Spotify...')

    url = 'https://developer.spotify.com/documentation/general/guides/scopes'
    html_data = requests.get(url).text
    soup = BeautifulSoup(html_data, 'html.parser')
    codes = soup.find_all('code')

    scopes = list(map(lambda c: c.text, codes))

    remaining_scopes = scopes
    chosen_scopes = []

    choice = None

    while choice != '' and len(remaining_scopes) > 0:
        msg = 'Scopes:\n'
        for idx in range(len(remaining_scopes)):
            msg += '[{}]\t{}\n'.format(idx, remaining_scopes[idx])

        print(msg[:-1])
        choice = input('Please add a scope [{}-{} or \'all\'] (\'<ENTER>\' if done): '.format(0, len(remaining_scopes) - 1))
        print('\n')
        if choice.lower() == 'all':
            chosen_scopes += remaining_scopes
            break
        try:
            choice = int(choice)

            scope = remaining_scopes[choice]
            chosen_scopes.append(scope)
            remaining_scopes.pop(choice)
        except:
            continue

    print('CURRENTLY CHOSEN SCOPES: {}'.format(len(chosen_scopes)), file=VERBOSE_STDOUT, flush=True)
    print(chosen_scopes, file=VERBOSE_STDOUT, flush=True)
        
    return chosen_scopes

def startFlaskHandler():
    cmd = 'python {}'.format(os.path.join(SCRIPT_DIR, 'app.py'))

    proc = subprocess.Popen(cmd.split(' '), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)

    return proc

def setupSpotify(clientid, clientsecret, configfile='secrets.conf'):
    if configfile == 'secrets.conf':
        configfile = os.path.join(SCRIPT_DIR, configfile)

    app_token = b64encode('{}:{}'.format(clientid, clientsecret).encode('utf-8')).decode('utf-8')
    print('APP TOKEN: {}'.format(app_token), file=VERBOSE_STDOUT, flush=True)

    scopes = getScopes()

    proc = startFlaskHandler()

    baseurl = 'https://accounts.spotify.com'

    redirect_uri = 'http://127.0.0.1:5000'

    params = {'client_id': clientid, 'response_type': 'code', 'redirect_uri': redirect_uri, 'scope': ' '.join(scopes)}

    url = baseurl + '/authorize' + '/?' + urllib.parse.urlencode(params)
    print(url)
    webbrowser.open_new(url)

    wait = True

    while wait is True:
        choice = input('Has the authentication code been retrieved? (Y/N): ').lower()
        if choice != 'y' and choice != 'n':
            print('Error! Please pick either \'Y\' or \'N\'.')
        elif choice == 'y':
            wait = False
        elif choice == 'n':
            waittime = 2
            print('Sleeping for {} seconds...'.format(waittime))
            time.sleep(waittime)

    proc.terminate()
    flask_stdout = proc.stdout.read()

    code_matches = re.findall(r"RECEIVED CODE: (.*)", flask_stdout)
    if len(code_matches) > 0:
        code = code_matches.pop()
    else:
        code = None

    if code is None:
        raise Exception('Did not successfully receive code!')

    payload = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri}

    headers = {'Authorization': 'Basic {}'.format(app_token)}

    res = requests.post(baseurl + '/api/token', data=payload, headers=headers)
    if res.status_code != 200:
        print(res.url, file=VERBOSE_STDOUT, flush=True)
        print(res.status_code, file=VERBOSE_STDOUT, flush=True)
        print(res.text, file=VERBOSE_STDOUT, flush=True)
        raise Exception('Failed to retrieve access token!')

    data = res.json()
    print(data, file=VERBOSE_STDOUT, flush=True)

    refresh_token = data.get('refresh_token')

    config = configparser.ConfigParser()
    config['Application Configuration'] = {'app token': app_token, 'refresh token': refresh_token}

    with open(configfile, 'w') as configfd:
        config.write(configfd)

    print('Successfully setup Spotify application!')
    print('Application Token and Refresh Token values are stored in {}'.format(configfile))

def showImage(url):
    data = urllib.request.urlopen(url)

    img = Image.open(data)
    imgcat.imgcat(img)

def printCurrentlyPlaying(data, showimg=False):
    if data.get('status', 'erorr') == 'success':
        if showimg is True:
            showImage(data.get('artwork'))

        msg = 'Now Playing:\n'
        msg += 'Track: {}\n'.format(data.get('track'))
        msg += 'Artist: {}\n'.format(data.get('artist'))
        msg += 'Album: {}\n'.format(data.get('album'))
        if data.get('playlist', None) is not None:
            msg += 'Playlist: {}\n'.format(data.get('playlist'))

        msg += 'URI: {}\n'.format(data.get('uri'))

        if data.get('playlist_uri', None) is not None:
            msg += 'Playlist URI: {}\n'.format(data.get('playlist_uri'))

        print(msg)
    else:
        raise Exception(data.get('error'))

def printControlPlayback(data):
    print(data.get('status'), data.get('status_code'), data.get('error', None))

def printDevices(data):
    print(data)

def printRecents(data):
    print('\n'.join(list(map(lambda s: '\'{}\' by \'{}\' - \'{}\''.format(s.get('track'), s.get('artist'), s.get('album')), data))))

class Spotify:
    VALID_OPERATIONS = {
        'playback': ['play', 'pause', 'next', 'previous', 'shuffle', 'repeat', 'queue', 'seek'],
        'playlist': ['add', 'remove']
    }

    def __init__(self, application_token, refresh_token):
        self.baseurl = 'https://{}.spotify.com/{}'
        self.apiurl = self.baseurl.format('api', 'v1')

        self.app_token = application_token
        self.refresh_token = refresh_token

        self.access_token = self.get_access_token()
        self.headers = {'Authorization': 'Bearer {}'.format(self.access_token)}

    def request_token(self):
        headers = {'Authorization': 'Basic {}'.format(self.app_token)}

        payload = {'grant_type': 'refresh_token', 'refresh_token': self.refresh_token}

        res = requests.post(self.baseurl.format('accounts', 'api') + '/token', headers=headers, data=payload)
        if res.status_code == 200:
            return res.json()
        else:
            print(res.json(), file=VERBOSE_STDOUT, flush=True)
            return res.json()

    def get_access_token(self):
        return self.request_token().get('access_token')

    def getCurrentUser(self):
        url = self.apiurl + '/me'

        res = requests.get(url, headers=self.headers)
        print(res.json(), file=VERBOSE_STDOUT, flush=True)
        data = res.json()

        if res.status_code == 200:
            data['status'] = 'connected'
        else:
            data['status'] = 'disconnected'

        return data

    def playlist(self, operation, playlist, songs, device=None):
        userplaylists = self.getPlaylists()
        playlists = list(map(lambda x: (x.get('name'), x.get('id')), userplaylists.get('items')))

        playlistid = None

        for name in list(map(lambda x: x[0], playlists)):
            if playlist in name:
                # playlist is in name list
                playlistid = playlists[list(map(lambda x: x[0], playlists)).index(name)][-1]

        if playlistid is None:
            if id in list(map(lambda x: x[-1], playlists)):
                # playlist is in id list
                playlistid = id
            else: 
                raise Exception('Invalid playlist name or id!')

        if operation not in self.VALID_OPERATIONS.get('playlist'):
            raise Exception('Invalid playlist operation!')

        if operation == 'add':
            pass
        elif operation == 'remove':
            return self.removeFromPlaylist(playlistid, songs, device=device)


    def getPlaylists(self):
        url = self.apiurl + '/users/{}/playlists'.format(self.getCurrentUser().get('id'))

        res = requests.get(url, headers=self.headers)

        data = {}
        data['status_code'] = res.status_code

        if res.status_code == 200:
            data['status'] = 'success'
            data.update(res.json())
        else:
            data['status'] = 'error'

        print(data, file=VERBOSE_STDOUT, flush=True)

        return data

    def getPlaylist(self, id):
        url = self.apiurl + '/playlists/{}'.format(id)

        res = requests.get(url, headers=self.headers)

        data = {}
        data['status_code'] = res.status_code

        if res.status_code == 200:
            data['status'] = 'success'
            data.update(res.json())
        else:
            data['status'] = 'error'

        print(data, file=VERBOSE_STDOUT, flush=True)

        return data

    def addToPlaylist(self, playlistid, songid):
        pass

    def removeFromPlaylist(self, playlistid, songids, device=None):
        url = self.apiurl + '/playlists/{}/tracks'.format(playlistid)
        print(url)

        payload = {'tracks': list({'uri': songid} for songid in songids)}
        print(payload)

        res = requests.delete(url, headers=self.headers, data=payload)

        data = {}
        data['status_code'] = res.status_code

        if res.status_code == 200:
            data['status'] = 'success'
            data.update(res.json())
        else:
            data['status'] = 'error'
            print(res.json())

        print(data, file=VERBOSE_STDOUT, flush=True)

        if device is not None:
            self.controlPlayback('next', device=device)

        return data

    def currentlyPlaying(self):
        url = self.apiurl + '/me/player/currently-playing'

        res = requests.get(url, headers=self.headers)
        print(res.status_code, file=VERBOSE_STDOUT, flush=True)
        if res.status_code == 200:
            data = res.json()

            print(data, file=VERBOSE_STDOUT, flush=True)

            return self._getSongData(data)
        elif res.status_code == 204:
            return {'status': 'error', 'error': 'No track currently playing'}

    def getPlayback(self):
        url = self.apiurl + '/me/player'

        res = requests.get(url, headers=self.headers)

        data = {'status_code': res.status_code}
        if res.status_code == 200:
            data['status'] = 'success'
            data.update(res.json())
        else:
            data['status'] = 'error'

        print(data, file=VERBOSE_STDOUT, flush=True)

        return data

    def controlPlayback(self, operation, device=None, uri=None, seekOffset=0):
        operation = operation.lower()
        if operation not in self.VALID_OPERATIONS['playback']:
            raise Exception('Invalid playback operation!')

        url = self.apiurl + '/me/player/{}'.format(operation)

        params = {}

        if device:
            deviceid = self._getDeviceId(device)

            params['device_id'] = deviceid

        if operation == 'shuffle':
            params['state'] = self.getPlayback().get('shuffle_state', False)
            params['state'] = not params['state']
        elif operation == 'repeat':
            params['state'] = self.getPlayback().get('repeat_state', False)
            params['state'] = 'context' if params['state'] == 'off' else 'off'
        elif operation == 'queue':
            params['uri'] = uri
        elif operation == "seek":
            song = self.currentlyPlaying()
            duration = int(song['raw']['duration_ms'])
            seekPos = round(duration * (seekOffset/4))
            params['position_ms'] = seekPos

        if operation == 'queue':
            res = requests.post(url, headers=self.headers, params=params)
        else:
            res = requests.put(url, headers=self.headers, params=params)

        data = {'status_code': res.status_code}
        if res.status_code == 204:
            data['status'] = 'success'
        else:
            data['status'] = 'error'

            if res.status_code == 404:
                data['error'] = 'device not found'
            elif res.status_code == 403:
                data['error'] = 'unable to perform operation: {}'.format(operation)
            else:
                data['error'] = 'undocumented error'

        print(data, file=VERBOSE_STDOUT, flush=True)

        return data

    def _getDevices(self):
        url = self.apiurl + '/me/player/devices'

        res = requests.get(url, headers=self.headers)
        
        data = {'status_code': res.status_code}
        if res.status_code == 200:
            data['status'] = 'success'

            data.update(res.json())
        else:
            data['status'] = 'error'

        print(data, file=VERBOSE_STDOUT, flush=True)

        return data

    def getDevices(self):
        data = self._getDevices()

        if data.get('status') == 'success':
            devices = {}
            for device in data.get('devices'):
                devices[device['name']] = device

            return devices
        else:
            raise Exception('Unable to retrieve devices')

    def _getDeviceId(self, device):
        devices = self.getDevices()

        deviceid = None

        if device in devices.keys():
            # input is device name
            deviceid = devices.get(device).get('id')
        else:
            # check if input is device id
            deviceid_matches = list(filter(lambda d: d.get('id') == device, devices))
            if len(deviceid_matches) > 0:
                deviceid = deviceid_matches[0]

        return deviceid

    def _recentlyPlayed(self, limit=20, before=None, after=None):
        url = self.apiurl + '/me/player/recently-played'

        params = {}
        if limit in range(1, 51):
            params['limit'] = limit

        if before and after is None:
            params['before'] = before
        elif after and before is None:
            params['after'] = after

        res = requests.get(url, headers=self.headers, params=params)

        data = {'status_code': res.status_code}
        if res.status_code == 200:
            data['status'] = 'success'

            data.update(res.json())
        else:
            data['status'] = 'error'

        print(data, file=VERBOSE_STDOUT, flush=True)

        return data

    def _getSongData(self, song_obj):
        context = song_obj.get('context', {})
        if context and context.get('type') == 'playlist':
            playlist_data = self.getPlaylist(song_obj.get('context', {}).get('href').split('/')[-1])
            playlist = playlist_data.get('name')
            playlist_uri = playlist_data.get('uri')
        else:
            playlist = None
            playlist_uri = None
        if 'item' in song_obj:
            song = song_obj.get('item', {})
        elif 'track' in song_obj:
            song = song_obj.get('track', {})

        images = song.get('album', {}).get('images', [{}])
        imgurl = images[1].get('url')

        track = song.get('name')
        artist = ', '.join(list(map(lambda x: x.get('name'), song.get('artists', [{}]))))
        album = song.get('album', {}).get('name')
        uri = song.get('uri')

        return {'status': 'success', 'artwork': imgurl, 'track': track, 'artist': artist, 'album': album, 'uri': uri, 'playlist': playlist, 'playlist_uri': playlist_uri, 'raw': song}

    def getRecentlyPlayed(self, limit=20, before=None, after=None):
        data = self._recentlyPlayed(limit=limit, before=before, after=after) 

        return list(map(lambda s: self._getSongData(s), data['items']))
    
    def __repr__(self):
        connected_user = self.getCurrentUser()
        user = connected_user.get('display_name', connected_user.get('error'))
        status = connected_user.get('status')
        profile = connected_user.get('images', []).pop().get('url')

        showImage(profile)

        return '<Spotify (\'{}\' - {})>'.format(user, status)

if __name__ == "__main__":
    parser = argparsejson.parse_arguments(os.path.join(SCRIPT_DIR, "commands.json"), prog=__file__)
    args = parser.parse_args()

    if args.verbose:
        VERBOSE_STDOUT = sys.stdout
    else:
        VERBOSE_STDOUT = open(os.devnull, 'w')

    print(args, file=VERBOSE_STDOUT, flush=True)

    if args.mode is None:
        parser.print_help()
    elif args.mode == 'setup':
        if args.clientid:
            clientid = args.clientid

        if args.clientsecret:
            clientsecret = args.clientsecret

        setupSpotify(clientid, clientsecret)
    else:
        config = parse_config()

        app_token = config.get('app_token')
        refresh_token = config.get('refresh_token')

        client = Spotify(app_token, refresh_token)

        if args.mode == 'status':
            if args.showimg:
                showimg = args.showimg
            else:
                showimg = False

            printCurrentlyPlaying(client.currentlyPlaying(), showimg)

        elif args.mode == 'playback':
            if args.playback:
                operation = args.playback
            else:
                operation = None

            if args.device:
                device = args.device
            else:
                device = None

            if operation == "queue" and args.uri:
                uri = args.uri
            else:
                uri = None

            if operation == "seek":
                seek = args.duration
            else:
                seek = 0

            status = client.controlPlayback(operation, device=device, uri=uri, seekOffset=seek)
            printControlPlayback(status)

        elif args.mode == 'playlist':
            print(args)
            if args.operation:
                operation = args.operation
            else:
                operation = None

            if args.nowplaying:
                nowplaying = args.nowplaying
            else:
                nowplaying = False

            if args.playlist:
                playlist = args.playlist
            else:
                playlist = None

            if args.song:
                song = args.song
            elif nowplaying is True:
                song = client.currentlyPlaying().get('uri')
            else:
                song = None

            if args.device:
                device = args.device
            else:
                device = None

            results = client.playlist(operation, playlist, [song], device=device)

        elif args.mode == 'devices':
            devices = client.getDevices()
            printDevices(devices)

        elif args.mode == 'user':
            if args.user == 'recents':
                if args.before:
                    before = args.before
                else:
                    before = None

                if args.after:
                    after = args.after
                else:
                    after = None

                if args.limit:
                    limit = args.limit
                else:
                    limit = None

                recents = client.getRecentlyPlayed(limit=limit, before=before, after=after)
                printRecents(recents)
            elif args.user == 'status':
                print(client)

    if not args.verbose:
        VERBOSE_STDOUT.close()
