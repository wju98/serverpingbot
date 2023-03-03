import discord
from tcping import Ping
from threading import Thread
from discord.ext import tasks
import sqlite3
import time
import asyncio
import config

"""
This discord bot will ping users when a Maplestory maintenance ends. Any user that reacts to the message generated by
"!react" will be on the list of people the bot will ping. The end of a maintenance is detected when all 3 login servers
are online after being in an offline state for at least 30 minutes. In order to be in an online state, all 3 login
servers must respond to a ping. If any login server fails to do so, the login servers are considered to be offline.

Maplestory's login servers:
LOGIN SERVER 1: ip address 34.215.62.60, port 8484
LOGIN SERVER 2: ip address 35.167.153.201, port 8484
LOGIN SERVER 3: ip address 52.37.193.138, port 8484
"""

IP_ADDRESSES = ['34.215.62.60', '35.167.153.201', '52.37.193.138']
channel_ids = [186575200609894400]
client = discord.Client()
client.online = False
client.offline_time = time.time() - 1800
connection = sqlite3.connect('react_messages.db')


@client.event
async def on_ready():
    """
    Called when the discord bot first starts up. Identifies whether or not the login servers are in an online or offline
    state and creates a database, if it doesn't already exist, for every message generated by "!react".

    :return: nothing
    """
    print('We have logged in as {0.user}'.format(client))
    client.online = get_server_status()
    if client.online:
        print('login servers are currently online')
    else:
        print('login servers are currently offline')

    c = connection.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS react_messages(message_id integer, channel_id integer, "
              "PRIMARY KEY (message_id))")
    connection.commit()
    c.close()
    monitor_server_status.start()


@client.event
async def on_message(message):
    """
    Called whenever a message appears in any of the text channels that can be viewed by the discord bot.

    :param message: Input from the user of the message that was typed in the text channel
    :return: nothing
    """
    if message.author == client.user:
        return

    if message.content.startswith('!react') and \
            (message.author.guild_permissions.administrator or message.author.id == 258064566456549387):
        """
        Generates a message that users react to in order to be added to the list of people that will be pinged when a
        Maplestory maintenance ends. Must be a server admin of the discord server to use this command.
        """
        embed = discord.Embed()
        embed_value = "React to this message to be pinged when a Maplestory maintenance ends."
        embed.add_field(name="Maintenance Ending Ping", value=embed_value, inline=False)
        embed_message = await message.channel.send(embed=embed)
        await embed_message.add_reaction('👍')

        c = connection.cursor()
        sql = "INSERT INTO react_messages(message_id, channel_id) VALUES(?, ?)"
        val = (embed_message.id, embed_message.channel.id)
        c.execute(sql, val)
        connection.commit()
        c.close()
        return

    if message.content.startswith('!ping') and message.author.id == 258064566456549387:
        """
        Pings all users that reacted to the message generated by "!react". Command can only be used my the creator of 
        this bot. For testing/demonstration pinging system.
        """
        await message_channels()
        return

    if message.content.startswith('!botstatistics') and message.author.id == 258064566456549387:
        """
        Displays stats about this discord bot, including number of discord server the bot is in, number of "!react"
        messages that were generated by this bot, the number of users that have reacted to the !react messages and
        lists out all the users who have reacted. Used for testing reaction system.
        """
        c = connection.cursor()
        c.execute(f"SELECT * FROM react_messages")
        react_messages = c.fetchall()
        c.close()
        users = await fetch_users(react_messages)

        number_of_servers = len(client.guilds)
        number_of_reacts = len(react_messages)
        number_of_users = len(users)
        all_users = ""
        for user in users:
            all_users += str(user) + " "
        stats = f"Number of Servers: {number_of_servers} \n" \
                f"Number of !react Messages: {number_of_reacts} \n" \
                f"Number of Users: {number_of_users} \n" + all_users
        await message.channel.send(stats)
        return


@tasks.loop(seconds=8)
async def monitor_server_status():
    """
    Monitors the state of all login servers every 10 seconds and updates their state.
    """
    new_status = get_server_status()
    if client.online != new_status:
        if new_status:
            print("login servers have just went online")
            if time.time() - client.offline_time > 1800:
                await ping_reacted_users()
                await message_channels()
        else:
            print("login servers have just went offline")
            client.offline_time = time.time()
        client.online = new_status
    else:
        if new_status:
            print("login servers are still online")
            await asyncio.sleep(1792)
        else:
            print("login servers are still offline")


async def message_channels():
    for channel_id in channel_ids:
        channel = client.get_channel(channel_id)
        await channel.send("Login servers have just went online. Maintenance has just ended.")


async def ping_reacted_users():
    """
    Pings all users that reacted to the message generated by "!react".
    """
    c = connection.cursor()
    c.execute(f"SELECT * FROM react_messages")
    react_messages = c.fetchall()
    c.close()
    users = await fetch_users(react_messages)
    count = 0

    for user in users:
        try:
            if user.id == 268580291054927875:
                await user.send(f"<@{user.id}> Hey Babe! Rise and shine! The game is up now!. It's time for you to pop "
                                f"a totem and start training while these burnings are HIGH!")
            else:
                await user.send(f"<@{user.id}> Login servers have just went online. Maintenance has just ended.")
        except discord.errors.DiscordException:
            print("User no longer shares server with bot and can't be pinged.")
            pass

        # Discord API has a rate limit of 50 requests per second, to prevent hitting the limit, this bot will only allow
        # 45 messages to be sent every 2 seconds.
        count += 1
        if count % 45 == 0:
            await asyncio.sleep(2)


async def fetch_users(react_messages):
    """
    Returns a set of all users that have a reaction to any of the "!react" messages.
    :param react_messages: A list of generated "!react" messages
    :return: A set of users that reacted to any of the "!react" messages
    """
    users = set()
    for rm in react_messages:
        message_id = rm[0]
        channel_id = rm[1]
        channel = client.get_channel(channel_id)
        try:
            react_message = await channel.fetch_message(message_id)
        except (discord.errors.NotFound, AttributeError):
            c = connection.cursor()
            sql = "DELETE FROM react_messages WHERE message_id = ?"
            val = (message_id,)
            c.execute(sql, val)
            connection.commit()
            c.close()
            print('"!react" message was deleted or bot was removed from server, "!react" message has been deleted')
            continue
        except discord.errors.Forbidden:
            print('"!react" message is in a channel that the bot does not have access to')
            continue
        for reaction in react_message.reactions:
            async for user in reaction.users():
                if user != client.user:
                    users.add(user)

    return users


def get_server_status():
    """
    Pings all 3 Maplestory login servers and determines whether the servers are online or offline.

    :return: True if all login servers are online, otherwise False.
    """
    result = []
    threads_list = []
    for ipaddress in IP_ADDRESSES:
        t = Thread(target=lambda q, arg1: result.append(check_for_response(arg1)), args=(result, ipaddress))
        t.start()
        threads_list.append(t)

    for t in threads_list:
        t.join()

    return False not in result


def check_for_response(ipaddress):
    """
    Determines whether we get a response when we ping the IP address given.

    :param ipaddress: The IP address given as a string that will be pinged.
    :return: True if we get a response from the ping, otherwise False.
    """
    ping = Ping(ipaddress, 8484, 2)
    try:
        ping.ping(1)
    except:
        return False
    return '100.00%' in ping.result.raw


client.run(config.TOKEN)
