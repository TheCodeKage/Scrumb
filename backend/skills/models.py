from django.contrib.auth.models import User
from django.db import models

# Create your models here.
class Skill(models.Model):
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=100)
    user = models.ManyToManyField(User, through="UserSkill")


class UserSkill(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    proficiency = models.PositiveSmallIntegerField(default=0)
