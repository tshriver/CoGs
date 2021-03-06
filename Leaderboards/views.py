import re
import json
import cProfile, pstats, io
from datetime import datetime, timedelta
from collections import OrderedDict

from django_generic_view_extensions import odf, datetime_format_python_to_PHP, DetailViewExtended, DeleteViewExtended, CreateViewExtended, UpdateViewExtended, ListViewExtended
from Leaderboards.models import Team, Player, Game, League, Location, Session, Rank, Performance, Rating, ALL_LEAGUES, ALL_PLAYERS, NEVER

from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone
from django.http import HttpResponse
from django.contrib.auth.models import Group
from django.core.serializers.json import DjangoJSONEncoder
from django.conf.global_settings import DATETIME_INPUT_FORMATS

# TODO: Fix timezone handling. By defaul in Django wwe us UTC but we want to enter sesisons in local time and see result sin local time.
#        This may need to be League hooked and/or Venue hooked, that is leagues specify a timezone and Venues can specfy one that overrides?
#        Either way when adding a session we don't know until the League and Venue are chosen what timezone to use.
#        Requires a postback on a League or Venue change? So we can render the DateTime and read box in the approriate timezone?
from django.utils.timezone import get_default_timezone_name, get_current_timezone_name

#TODO: Add account security, and test it
#TODO: Once account security is in place a player will be in certain leagues, restrict some views to info related to those leagues.
#TODO: Put a filter in the menu bar, for selecting a league, and then restrict a lot of views only to that league's data.

#TODO: Add testing: https://docs.djangoproject.com/en/1.10/topics/testing/tools/

#===============================================================================
# Some support routines
#===============================================================================

def index(request):   
    return render(request, 'CoGs/base.html')

def is_registrar(user):
    return user.groups.filter(name='registrars').exists()

#===============================================================================
# Form processing specific to CoGs
#===============================================================================

def updated_user_from_form(user, request):
    '''
    Updates a user object in the database (from the Django auth module) with information from the submitted form, specific to CoGs
    '''
    POST = request.POST
    registrars = Group.objects.get(name='registrars')

    user.username = POST['name_nickname']       # TODO: nicknames can have spaces, does the auth model support usernames with spaces? 
    user.first_name = POST['name_personal']
    user.last_name = POST['name_family']
    user.email = POST['email_address']
    user.is_staff = 'is_staff' in POST
    if 'is_registrar' in POST:
        if not is_registrar(user):
            user.groups.add(registrars)
    else:
        if is_registrar(user):
            registrars.user_set.remove(user)
    user.save

def process_submitted_model(self):
    '''
    When a model form is posted, this function will perform model specific updates, based on the model specified in the form (kwargs) as "model"
    
    It will be running inside a transaction and can bail with an IntegrityError if something goes wrong achieving a rollback.
    
    This is executed inside a transaction as a callback from generic_view_extensions CreateViewExtended and UpdateViewExtended,
    so it can throw an Integrity Error to roll back the transaction. This is important if it is trying to update a number of 
    models at the same time that are all related. The integrity of relations after the save should be tested and if not passed,
    then throw an IntegrityError.   
    '''
    model = self.model._meta.model_name

    if model == 'player':
        pass # updated_user_from_form(...) # TODO: Need when saving users update the auth model too.
    elif model == 'session':
    # TODO: When saving sessions, need to do a confirmation step first, reporting the impacts.
    #       Editing a session will have to force recalculation of all the rating impacts of sessions
    #       all the participating players were in that were played after the edited session.
    #    A general are you sure? system for edits is worth implementing.
    
    # TODO: When saving a session sort ranks numerically and substitude by 1, 2, 3, 4 ... to ensure victors are always identifes by rank 1 and rank is the ordinal.
    #        Silently enforcing this is better than requiring the user to. The form can support any integers that indicate order.

        session = self.object
        
        # TODO: Bug here?
        # session.ranks for some reason is None
        # even after a session.reload_from_db
        # So can fetch the ranks explicitly. 
        # But something with the Django field "ranks" is broken
        # And not sure if it's a local issue or a bug in Django.
        #
        # If we sort them in the order that they were created then we have 
        # a list that is the same order as the TeamPlayers list which we 
        # we build below, because all are created in order of the submitted
        # form fields.
        #
        # We can sort on pk or creeated_on for the same expected result.
        ranks = Rank.objects.filter(session=session.pk).order_by('created_on')
        
        # TODO: Sort Ranks, and map onto a list of 1, 2, 3, 4 ... 
        
        team_play = session.team_play

        if team_play:
            # Get the player list for submitted teams and the name.
            # Find a team with those players
            # If the name is not blank or Team n then update the team name
            # If it doesn't exist, create a team and give it the specified name or null of Team n

            # Work out the total number of players and initialize a TeamPlayers and teamRank records
            num_teams = int(self.request.POST["num_teams"])
            num_players = 0
            TeamPlayers = []
            for t in range(num_teams):
                num_team_players = int(self.request.POST["Team-%d-num_players" % t])
                num_players += num_team_players
                TeamPlayers.append([])

            # Populate the TeamPlayers record (i.e. work out which players are on the same team)
            for p in range(num_players):
                player = int(self.request.POST["Performance-%d-player" % p])
                team_num = int(self.request.POST["Performance-%d-team_num" % p])
                TeamPlayers[team_num].append(player)

            # For each team now, find it, create it , fix it as needed and associate it with the appropriate Rank just created
            for t in range(num_teams):
                # Rank objects were saved in the database in the order of the 
                # TeamRanks list. The TeamPlayers list has a matching list of  
                # player Ids. t is stepping through these lists. So the rank object 
                # we want to attach this team to is simply: 
                rank = ranks[t]

                # Similarly the team players list is in the same order
                team_players = TeamPlayers[t]

                # The name submitted for this team 
                new_name = self.request.POST["Team-%d-name" % t]

                # Find the team object that has these specific players.
                # Filter by count first and filter by players one by one.
                teams = Team.objects.annotate(count=Count('players')).filter(count=len(team_players))
                for player in team_players:
                    teams = teams.filter(players=player)

                # If not found, then create a team object with those players and 
                # link it to the rank object
                if len(teams) == 0:
                    team = Team.objects.create()

                    for player_id in team_players:
                        player = Player.objects.get(id=player_id)
                        team.players.add(player)

                    if new_name and not re.match("^Team \d+$", new_name, re.IGNORECASE):
                        team.name = new_name
                        team.save()

                    rank.team=team
                    rank.save()

                # If one is found, then link it to the approriate rank object and 
                # check its name against the submission (updating if need be)
                elif len(teams) == 1:
                    team = teams[0]

                    if new_name and not re.match("^Team \d+$", new_name, re.IGNORECASE) and new_name != team.name :
                        team.name = new_name
                        team.save()

                    if (rank.team != team):
                        rank.team=team
                        rank.save()

                # Weirdness, we can't legally have more than one team with the same set of players in the database
                else:
                    raise ValueError("Database error: More than one team with same players in database.")

        # Calculate and save the TrueSkill rating impacts to the Performance records
        session.calculate_trueskill_impacts()
        
        # Then update the ratings for all players of this game
        Rating.update(session)
        
        # Now check the integrity of the save. For a sessions, this means that:
        #
        # If it is a team_play session:
        #    The game supports team_play
        #    The ranks all record teams and not players
        #    There is one performance object for each player (accessed through Team).
        # If it is not team_play:
        #    The game supports individua_play
        #    The ranks all record players not teams
        #    There is one performance record for each player/rank
        # The before trueskill values are identical to the after trueskill values for each players 
        #     prior session on same game.
        # The rating for each player at this game has a playcount that is one higher than it was!
        # The rating has recorded the global trueskill settings and the Game trueskill settings reliably.
        #
        # TODO: Do these checks. Then do test of the transaction rollback and error catch by 
        #       simulating an integrity error.  

def context_provider(self, context):
    '''
    Updates the provided context with CoGs specific items 
    :param context: The context to update, a dictionary.
    
    Specifically The session form when editing existing sessions has a game already known,
    and this game has some key properties that the form wants to know about. Namely:
    
    individual_play: does this game permit indiviual play
    team_play: does this game support team play
    min_players: minimum number of players for this game
    max_players: manimum number of players for this game
    min_players_per_team: minimum number of players in a team in this game. Relevant only if team_play supported.
    max_players_per_team: maximum number of players in a team in this game. Relevant only if team_play supported.
    
    Clearly altering the game should trigger a relaod of this metadata for the newly selected game.
    See ajax_Game_Properties below for that. 
    '''
    model = self.model._meta.model_name
    
    if model == 'session':
        Default = Game()
        context['game_individual_play'] = json.dumps(Default.individual_play)
        context['game_team_play'] = json.dumps(Default.team_play)
        context['game_min_players'] = Default.min_players
        context['game_max_players'] = Default.max_players
        context['game_min_players_per_team'] = Default.min_players_per_team
        context['game_max_players_per_team'] = Default.max_players_per_team
        
        session = self.object        
                
        if session:
            game = session.game
            if game:
                context['game_individual_play'] = json.dumps(game.individual_play) # Python True/False, JS true/false 
                context['game_team_play'] = json.dumps(game.team_play)
                context['game_min_players'] = game.min_players
                context['game_max_players'] = game.max_players
                context['game_min_players_per_team'] = game.min_players_per_team
                context['game_max_players_per_team'] = game.max_players_per_team

#===============================================================================
# Customize Generic Views for CoGs
#===============================================================================
# TODO: Test that this does validation and what it does on submission errors

class view_Add(CreateViewExtended):
    # TODO: Should be atomic with an integrity check on all session, rank, performance, team, player relations.
    template_name = 'CoGs/form_data.html'
    operation = 'add'
    extra_context = context_provider
    post_processor = process_submitted_model

# TODO: Test that this does validation and what it does on submission errors

class view_Edit(UpdateViewExtended):
    # TODO: Must be atomic and in such a way that it tests if changes haveintegrity.
    #       notably if a session changes from indiv to team mode say or vice versa,
    #       there is a notable impact on rank objects that could go wrong and we should
    #       check integrity. 
    #       Throw:
    #        https://docs.djangoproject.com/en/1.10/ref/exceptions/#django.db.IntegrityError
    #       if an integrity error is found in such a transaction (or any transaction).
    template_name = 'CoGs/form_data.html'
    operation = 'edit'
    extra_context = context_provider
    post_processor = process_submitted_model

class view_Delete(DeleteViewExtended):
    # TODO: Should be atomic for sesssions as a session delete needs us to delete session, ranks and performances
    template_name = 'CoGs/delete_data.html'
    operation = 'delete'
    format = odf.normal

class view_List(ListViewExtended):
    template_name = 'CoGs/list_data.html'
    operation = 'list'
    # TODO: Add message reporting how many items listed and the filter used.

class view_Detail(DetailViewExtended):
    template_name = 'CoGs/view_data.html'
    operation = 'view'
    format = odf.normal

#===============================================================================
# The Leaderboards view. What it's all about!
#===============================================================================

def view_Leaderboards(request): 
    '''
    The raison d'etre of the whole site, this view presents the leaderboards. 
    '''
    # FIXME: Respond to GET request specifing columns, league and changed_since
    # FIXME: Add a league filter drop selector and present the leaderboards for the selected league
    # FIXME: Add a date_time selection for changed_since, and present only leaderboards changed since that date (so for games with sessions on or after then)
    
    # NOTE: request.GET is a dict of the Get parameters.
    # TODO: Add a league and player and maybe a date time widget to the context somehow (that could)
    # Or actually just a list of leagues and players, that's better. Form can build the controls.
    # Should just add the GET params to context so that the form can select the the right elements.

    # Get list of leagues, (pk, name) tuples.
    leagues = [(ALL_LEAGUES, 'ALL')] 
    leagues += [(x.pk, str(x)) for x in League.objects.all()]
    league = request.GET['league'] if 'league' in request.GET else ALL_LEAGUES
    
    # Get list of players, (pk, name) tuples.
    players = [(ALL_PLAYERS, 'ALL')] 
    if 'league' in request.GET:
        players += [(x.pk, str(x)) for x in Player.objects.filter(leagues__pk=league)]
    else:   
        players += [(x.pk, str(x)) for x in Player.objects.all()]
    player = request.GET['player'] if 'player' in request.GET else ALL_PLAYERS

    # TODO: Be robust against bad formats! 
    changed_since = parser.parse(request.GET['changed_since'] if 'changed_since' in request.GET else NEVER)

    leaderboard = {}
    plays = {}
    sessions = {}
    leaderboards = []
    
    for game in Game.objects.all():
        if league == ALL_LEAGUES or game.leagues.filter(pk=league).exists():
            lb = game.leaderboard(league, player, changed_since, indexed=True)
            if not lb is None: 
                leaderboard[game] = lb
                plays[game] = game.global_plays['total']      
                sessions[game] = game.global_sessions.count() 
    
    # Present leaderboards as a sorted list by a play count (selected above)
    for game in sorted(plays, key=plays.__getitem__, reverse=True):
        leaderboards.append((game.pk, game.name, plays[game], sessions[game], leaderboard[game]))

    # TODO: Make this more robust against illegal PKs. The whole view should be graceful if sent a bad league or player.
    try:
        P = Player.objects.get(pk=player)
    except:
        P = None

    try:
        L = League.objects.get(pk=league)
    except:
        L = None
        
    if player == ALL_PLAYERS:
        if league == ALL_LEAGUES:
            title = "Global Leaderboards"
        else:
            title = "Leaderboards for the {} league".format(L)
    else:
        if league == ALL_LEAGUES:
            title = "Leaderboards for {}".format(P)
        else:
            title = "Leaderboards for {} in the {} league".format(P, L)        

    c = {'title': title,
         'leaderboards': json.dumps(leaderboards, cls=DjangoJSONEncoder),
         'leagues': json.dumps(leagues, cls=DjangoJSONEncoder),
         'players': json.dumps(players, cls=DjangoJSONEncoder),
         'league': json.dumps(league),
         'player': json.dumps(player),
         'changed_since': json.dumps(str(changed_since)),
         'ALL_LEAGUES': json.dumps(ALL_LEAGUES), 
         'ALL_PLAYERS': json.dumps(ALL_PLAYERS), 
         'now': timezone.now(),
         'default_datetime_input_format': datetime_format_python_to_PHP(DATETIME_INPUT_FORMATS[0])}
    
    return render(request, 'CoGs/view_leaderboards.html', context=c)

def ajax_Game_Properties(request, pk):
    '''
    A view that returns the basic game properties needed by the Session form to make sensible rendering decisions.
    '''
    game = Game.objects.get(pk=pk)
    
    props = {'individual_play': game.individual_play, 
             'team_play': game.team_play,
             'min_players': game.min_players,
             'max_players': game.max_players,
             'min_players_per_team': game.min_players_per_team,
             'max_players_per_team': game.max_players_per_team
             }
      
    return HttpResponse(json.dumps(props))

#===============================================================================
# Special sneaky fixerupper and diagnostic view for testing code snippets
#===============================================================================

def view_CheckIntegrity(request):
    '''
    Check integrity of database
    
    The check_integrity routines on some models all work with assertions 
    and raise exceptions when integrity errors are found. So this will bail 
    on the first error, and outputs will be on the console not sent to the 
    browser.
    
    All needs some serious tidy up for a productions site.    
    '''
    
    print("Checking all Ratings for internal integrity.", flush=True)
    for R in Rating.objects.all():
        print(R, flush=True)
        R.check_integrity()
    
    print("Checking all Performances for internal integrity.", flush=True)
    for P in Performance.objects.all():
        print(P, flush=True)
        P.check_integrity()
    
    print("Checking all Sessions for internal integrity.", flush=True)
    for S in Session.objects.all():
        print(S, flush=True)
        S.check_integrity()
        
    return HttpResponse("Passed All Integrity Tests")

def view_RebuildRatings(request):
    html = rebuild_ratings()
    return HttpResponse(html)

def view_Fix(request):

# DONE: Used this to create Performance objects for existing Rank objects
#     sessions = Session.objects.all()
#
#     for session in sessions:
#         ranks = Rank.objects.filter(session=session.id)
#         for rank in ranks:
#             performance = Performance()
#             performance.session = rank.session
#             performance.player = rank.player
#             performance.save()

# Test the rank property of the Performance model
#     table = '<table border=1><tr><th>Performance</th><th>Rank</th></tr>'
#     performances = Performance.objects.all()
#     for performance in performances:
#         table = table + '<tr><td>' + str(performance.id) + '</td><td>' + str(performance.rank) + '</td></tr>'
#     table = table + '</table>'

    #html = force_unique_session_times()
    #html = rebuild_ratings()
    #html = import_sessions()
    
    
    html = "Success"
    
    return HttpResponse(html)

import csv
from dateutil import parser
from django_generic_view_extensions import hstr

def import_sessions():
    title = "Import CoGs scoresheet"
    
    result = ""
    sessions = []
    with open('/home/bernd/workspace/CoGs/Seed Data/CoGs Scoresheet - Session Log.csv', newline='') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=',', quotechar='"')
        for row in reader:
            date_time = parser.parse(row["Date"])
            game = row["Game"].strip()
            ranks = {
                row["1st place"].strip(): 1,
                row["2nd place"].strip(): 2,
                row["3rd place"].strip(): 3,
                row["4th place"].strip(): 4,
                row["5th place"].strip(): 5,
                row["6th place"].strip(): 6,
                row["7th place"].strip(): 7
                }
            
            tie_ranks = {}
            for r in ranks:
                if ',' in r:
                    rank = ranks[r]
                    players = r.split(',')
                    for p in players:
                        tie_ranks[p.strip()] = rank
                else:
                    tie_ranks[r] = ranks[r]
                    
            session = (date_time, game, tie_ranks)
            sessions.append(session)

    # Make sure a Game and Player object exists for each game and player
    missing_players = []
    missing_games = []
    for s in sessions:
        g = s[1]
        try:
            Game.objects.get(name=g)
        except Game.DoesNotExist:
            if g and not g in missing_games:
                missing_games.append(g)
        except Game.MultipleObjectsReturned:
            result += "{} exists more than once\n".format(g)
        
        for p in s[2]:
            try:
                Player.objects.get(name_nickname=p)
            except Player.DoesNotExist:
                if p and not p in missing_players:
                    missing_players.append(p)
            except Player.MultipleObjectsReturned:
                result += "{} exists more than once\n".format(p)
            
    if len(missing_games) == 0 and len(missing_players) == 0:
        result += hstr(sessions)
        
        Session.objects.all().delete()
        Rank.objects.all().delete()
        Performance.objects.all().delete()
        Rating.objects.all().delete()
        Team.objects.all().delete()
        
        for s in sessions:
            session = Session()
            session.date_time = s[0]
            session.game = Game.objects.get(name=s[1])
            session.league = League.objects.get(name='Hobart')
            session.location = Location.objects.get(name='The Big Blue House')
            session.save()
            
            for p in s[2]:
                if p:
                    rank = Rank()
                    rank.session = session
                    rank.rank = s[2][p]
                    rank.player = Player.objects.get(name_nickname=p)
                    rank.save()
    
                    performance = Performance()
                    performance.session = session
                    performance.player = rank.player
                    performance.save()
                            
            Rating.update(session)
    else:
        result += "Missing Games:\n{}\n".format(hstr(missing_games))
        result += "Missing Players:\n{}\n".format(hstr(missing_players))
            
    now = datetime.now()
            
    return "<html><body<p>{0}</p><p>It is now {1}.</p><p><pre>{2}</pre></p></body></html>".format(title, now, result)

def rebuild_ratings():
    title = "Rebuild of all ratings"
    pr = cProfile.Profile()
    pr.enable()
    
    Rating.rebuild_all()
    pr.disable()
    
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats()
    result = s.getvalue()
        
    now = datetime.now()

    return "<html><body<p>{0}</p><p>It is now {1}.</p><p><pre>{2}</pre></p></body></html>".format(title, now, result)
    
def force_unique_session_times():
    '''
    A quick hack to scan through all sessions and ensure none have the same session time
    # TODO: Enforce this when adding or editing sessions because Trueskill is temporal
    # TODO: Technically two game sessions can gave the same time, just not two session involving the same game and a common player. 
    #       This is because the Trueskill for that player at that game needs to have temporally ordered game sessions
    '''
 
    title = "Forced Unique Session Times"
    result = ""
   
    sessions = Session.objects.all().order_by('date_time')
    for s in sessions:
        coincident_sessions = Session.objects.filter(date_time=s.date_time)
        if len(coincident_sessions)>1:
            offset = 1
            for sess in coincident_sessions:
                sess.date_time = sess.date_time + timedelta(seconds=offset)
                sess.save()
                result += "Added {} to {}\n".format(offset, sess)
                offset += 1 

    now = datetime.now()

    return "<html><body<p>{0}</p><p>It is now {1}.</p><p><pre>{2}</pre></p></body></html>".format(title, now, result)      
