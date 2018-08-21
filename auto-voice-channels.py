import os
import json
import discord
import asyncio
from datetime import datetime
from time import time

last_channel = None
script_dir = os.path.dirname(os.path.realpath(__file__))
script_dir = script_dir+('/' if not script_dir.endswith('/') else '')

def read_json(fp):
    with open(fp, 'r') as f:
        data = json.load(f)
    return data

def write_json(fp, data):
    d = os.path.dirname(fp)
    if not os.path.exists(d):
        os.makedirs(d)
    with open(fp, 'w') as f:
        f.write(json.dumps(data, f, indent=4, sort_keys=True))

def get_config():
    global script_dir
    cf = os.path.join(script_dir, 'config.json')
    if not os.path.exists(cf):
        print ("Config file doesn't exist!")
        import sys
        sys.exit(0)
    return read_json(cf)

config = get_config()

def get_serv_settings(serv_id):
    global script_dir
    fp = os.path.join(script_dir, 'guilds', str(serv_id)+'.json')
    if not os.path.exists(fp):
        write_json(fp, read_json(os.path.join(script_dir, 'default_settings.json')))
    return read_json(fp)

def set_serv_settings(serv_id, settings):
    global script_dir
    fp = os.path.join(script_dir, 'guilds', str(serv_id)+'.json')
    return write_json(fp, settings)

def ldir(o):
    ''' Get all attributes/functions of an object, return them as a string in a nice format '''
    return '[\n'+(',\n'.join(dir(o)))+'\n]'

def fmsg(m):
    # Format message to display in a code block
    s = '```\n'
    s += str(m)
    s += '\n```'
    return s

def strip_quotes(s):
    chars_to_strip = ['\'', '"', ' ']
    if s:
        while s[0] in chars_to_strip:
            if len(s) <= 1:
                break
            s = s[1:]
        while s[-1] in chars_to_strip:
            if len(s) <= 1:
                break
            s = s[:-1]
    return s

def ascii_only(s):
    ns = ""
    printable_chars = list([chr(i) for i in range(32,127)])
    for c in s:
        if c in printable_chars:
            ns += c
        else:
            ns += '_'
    return ns

def log(msg, guild=None):
    text = datetime.now().strftime("%Y-%m-%d %H:%M")
    text += ' '
    if guild:
        text += '['+guild.name+']'
        text += ' '
    text += str(ascii_only(msg))
    print(text)

async def echo (msg, channel='auto', guild=None):
    global last_channel
    if channel == 'auto':
        channel = last_channel
    elif channel == None:
        log(msg, guild)
        return
    else:
        last_channel = channel

    max_chars = 1950  # Discord has a character limit of 2000 per message. Use 1950 to be safe.
    msg = str(msg)
    if len(msg) < max_chars:
        await catch_http_error(channel.send, msg)
    else:
        # Send message in chunks if it's longer than max_chars
        chunks = list([msg[i:i+max_chars] for i in range(0, len(msg), max_chars)])
        for c in chunks:
            await catch_http_error(channel.send, c)
    return

async def catch_http_error (function, *args, **kwargs):
    try:
        if args or kwargs:
            if args and not kwargs:
                r = await function(*args)
            elif kwargs and not args:
                r = await function(**kwargs)
            else:
                r = await function(*args, **kwargs)
        else:
            r = await function()
        return r
    except discord.errors.HTTPException:
        import traceback
        print(traceback.format_exc())
        log ("   !! ENCOUNTERED HTTP ERROR IN FUNC " + function.__name__ + " !!")

async def get_channel_game(channel):
    settings = get_serv_settings(channel.guild.id)
    games = {}
    for m in channel.members:
        if m.activity and not m.bot:
            gname = m.activity.name
            if gname in settings['aliases']:
                gname = settings['aliases'][gname]
            if gname in games:
                games[gname] += 1
            else:
                games[gname] = 1

    if not games:
        return "General"

    games_l = list((x, games[x]) for x in games)  # Convert dict to 2D list
    games_l.sort(key=lambda c: c[1], reverse=True)  # Sort by most players
    biggest_game, most_players = games_l[0]
    gnames = [biggest_game]
    games_l = games_l[1:]  # remaining games (excluding most popular one)
    for gn, gp in games_l:
        if gp == most_players:
            gnames.append(gn)
    if len(gnames) > 2:
        # More than 2 games with the same number of players
        return "General"
    else:
        return ', '.join(gnames)

def get_secondaries(guild):
    settings = get_serv_settings(guild.id)
    return list([x for y in list(settings['auto_channels'].values()) for x in y])

async def create_primary(guild, cname):
    c = await guild.create_voice_channel(cname)

    settings = get_serv_settings(guild.id)
    settings['auto_channels'][c.id] = []
    set_serv_settings(guild.id, settings)

    return c

async def create_secondary(guild, primary):
    # Create voice channel above primary one and return it
    
    settings = get_serv_settings(guild.id)

    c = await guild.create_voice_channel("⌛", category=primary.category)

    settings['auto_channels'][str(primary.id)].append(c.id)
    set_serv_settings(guild.id, settings)


    # Channel.position is relative to channels of any type, but Channel.edit(position) is relative to channels of that type. So we need to find that first.
    true_primary_position = 0
    voice_channels = [x for x in c.guild.channels if isinstance(x, type(c))]
    voice_channels.sort(key=lambda c: c.position)
    for x in voice_channels:
        if x.id == primary.id:
            break
        true_primary_position += 1

    # print()
    # print("P", primary.position)
    # print("PT", true_primary_position)
    # print("S", c.position)
    # max_channels = len(voice_channels)
    # print("M", max_channels)
    try:
        await c.edit(position = max(true_primary_position, 0))
    except discord.InvalidArgument:
        import traceback
        # Sometimes it seems to fail for no reason, claiming there are fewer channels than primary.position.
        # Probably don't need this since using true_primary_position, but keeping it for just in case.
        traceback.print_exc()
        print("Ignoring error...")
    # print("N", c.position)

    return c

async def delete_secondary(guild, channel):
    log("Deleting "+channel.name, guild)
    await channel.delete()
    settings = get_serv_settings(guild.id)
    for p in settings['auto_channels']:
        for s in settings['auto_channels'][p]:
            if s == channel.id:
                settings['auto_channels'][p].remove(s)
    set_serv_settings(guild.id, settings)



async def main_loop_func(guild, wait_first=True):
    # start_time = time()
    # print('\n'+guild.name, "tick")

    # TODO don't assume all join/leave events will be cought. Create secondaries if anyone is found in primaries.

    settings = get_serv_settings(guild.id)
    if not settings['enabled']:
        return

    if wait_first:
        global config
        await asyncio.sleep(config['background_interval'])

    # Delete empty secondaries, in case they didn't get caught somehow (e.g. errors, downtime)
    secondaries = get_secondaries(guild)
    voice_channels = [x for x in guild.channels if isinstance(x, discord.VoiceChannel)]
    for v in voice_channels:
        if v.name != "⌛":  # Ignore secondary channels that are currently being created
            if v.id in secondaries:
                if not v.members:
                    await delete_secondary(guild, v)

    # Update secondary channel names
    settings = get_serv_settings(guild.id)  # Need fresh in case some were deleted
    secondaries = []
    for p in settings['auto_channels']:
        for sid in settings['auto_channels'][p]:
            s = client.get_channel(sid)
            secondaries.append(s)
    i = 0
    secondaries = sorted(secondaries, key=lambda x: x.position)
    for s in secondaries:
        i += 1
        gname = await get_channel_game(s)
        cname = settings['channel_name_template'].replace('##', '#'+str(i)).replace('@@game_name@@', gname)
        if s.name != cname:
            log("Renaming "+s.name+" to "+cname, guild)
            await s.edit(name=cname)

    # end_time = time()
    # print(guild.name, "  tock", '{0:.3f}'.format(end_time-start_time)+'s')
    return


class MyClient(discord.Client):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # create the background task and run it in the background
        self.bg_task = self.loop.create_task(self.background_task())

    async def on_ready(self):
        print ('Logged in as')
        print (self.user.name)
        print (self.user.id)
        curtime = datetime.now().strftime("%Y-%m-%d %H:%M")
        print (curtime)
        print ('-'*len(str(self.user.id)))
        for s in self.guilds:
            await main_loop_func(s, wait_first=False)  # Run once initially. Background task doesn't like printing errors :/

    async def background_task(self):
        await self.wait_until_ready()
        while not self.is_closed():
            for s in self.guilds:
                await main_loop_func(s)

client = MyClient()

@client.event
async def on_message(message):
    if message.author == client.user:
        # Don't respond to self
        return

    # Commands
    prefix = 'avc-'
    if message.content.lower().startswith(prefix):
        msg = message.content[4:]  # Remove prefix
        split = msg.split(' ')
        cmd = split[0].lower()
        params = split[1:]
        params_str = ' '.join(params)

        guild = message.guild
        channel = message.channel
        settings = get_serv_settings(guild.id)

        # Restricted commands
        user_role_ids = list([r.id for r in message.author.roles])
        has_permission = not settings['requiredrole'] or settings['requiredrole'] in user_role_ids
        if has_permission:
            if cmd == 'enable':
                if settings['enabled']:
                    await echo("Already enabled. Use '"+prefix+"disable' to turn off.", channel)
                else:
                    await echo("Enabling auto voice channels. Turn off with '"+prefix+"disable'.", channel)
                    settings['enabled'] = True
                    set_serv_settings(guild.id, settings)
                return

            elif cmd == 'disable':
                if not settings['enabled']:
                    await echo("Already disabled. Use '"+prefix+"enable' to turn on.", channel)
                    log("Enabling", guild)
                else:
                    await echo("Disabling auto voice channels. Turn on again with '"+prefix+"enable'.", channel)
                    log("Disabling", guild)
                    settings['enabled'] = False
                    set_serv_settings(guild.id, settings)
                return

            elif cmd == 'listroles':
                username = strip_quotes(params_str)
                if username:
                    # Show roles of particular user if param is provided
                    found_user = False
                    for m in guild.members:
                        if m.name == username:
                            roles = m.roles
                            found_user = True
                            break
                    if not found_user:
                        await echo ("There is no user named \"" + username + "\"")
                        return
                else:
                    # If no param is provided, show all roles in server
                    roles = guild.roles

                l = ["ID" + ' '*18 + "\"Name\"  (Creation Date)"]
                l.append('='*len(l[0]))
                roles = sorted(roles, key=lambda x: x.created_at)
                for r in roles:
                    l.append(str(r.id)+"  \""+r.name+"\"  (Created on "+r.created_at.strftime("%Y/%m/%d")+")")
                await echo('\n'.join(l), channel)
                return

            elif cmd == 'restrict':
                role_id = strip_quotes(params_str)
                if not role_id:
                    await echo ("You need to specifiy the id of the role. Use '"+prefix+"listroles' to see the IDs of all roles, then do '"+prefix+"restrict 123456789101112131'", channel)
                else:
                    valid_ids = list([str(r.id) for r in guild.roles])
                    if role_id not in valid_ids:
                        await echo (valid_ids, channel)
                        await echo (role_id + " is not a valid id of any existing role. Use '"+prefix+"listroles' to see the IDs of all roles.", channel)
                    else:
                        role = None
                        for r in guild.roles:
                            if str(r.id) == role_id:    
                                role = r
                                break
                        if role not in message.author.roles:
                            await echo ("You need to have this role yourself in order to restrict commands to it.", channel)
                        else:
                            settings['requiredrole'] = role.id
                            set_serv_settings(guild.id, settings)
                            await echo ("From now on, most commands will be restricted to users with the \"" + role.name + "\" role.", channel)
                return

            elif cmd == 'create':
                ''' Create a new primary channel '''
                default_name = "➕ New Session"
                await create_primary(guild, default_name)
                await echo ("A new voice channel called \"" + default_name + "\" has been created. You can now move it around, rename it, etc.\n\nWhenever a user enters this voice channel, a new voice channel will be created above it for them, and they will automatically be moved to it.\nWhen that channel is empty, it will be deleted automatically.", channel)
                return

            elif cmd == 'alias':
                gsplit = params_str.split('>>')
                if len(gsplit) != 2 or not gsplit[0] or not gsplit[-1]:
                    await echo("Incorrect syntax for alias command. Should be: '"+prefix+"alias [Actual game name] >> [New name]' (without square brackets).", channel)
                else:
                    gname = strip_quotes(gsplit[0])
                    aname = strip_quotes(gsplit[1])
                    oname = gname
                    if gname in settings['aliases']:
                        oaname = settings['aliases'][gname]
                        oname = oaname
                        await echo("'" + gname + "' already has an alias ('" + oaname + "'), it will be replaced with '" + aname + "'.", channel)
                    else:
                        await echo("'" + gname + "' will now be shown as '" + aname + "'.", channel)
                    settings['aliases'][gname] = aname
                    set_serv_settings(guild.id, settings)

@client.event
async def on_voice_state_update(member, before, after):
    # This event is called every time someone joins/leaves a voice channel

    # Find which server this event happened in
    guild = None
    if before.channel:
        guild = before.channel.guild
    elif after.channel:
        guild = after.channel.guild

    settings = get_serv_settings(guild.id)
    if not settings['enabled']:
        return

    if after.channel:
        if str(after.channel.id) in settings['auto_channels']:
            log("Creating channel for " + member.name, guild)
            s = await create_secondary(guild, after.channel)
            await member.move_to(s)
            # await main_loop_func(guild, wait_first=False)

    if before.channel:
        secondaries = get_secondaries(guild)
        if before.channel.id in secondaries:
            if not before.channel.members:
                await delete_secondary(guild, before.channel)


client.run(config['token'])
